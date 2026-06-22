"""Django Q2 task: send a single notification to one user.

This task is what ``notifications.services.enqueue_*`` schedules.
It reads the user's notification preferences (``notify_push``,
``notify_email``) and ``push_token`` registration, then dispatches
via:

- Expo Push (``notifications.expo_client``) when the user opted in
  to push and has a token registered.
- Resend / SMTP email via ``django.core.mail.send_mail`` when the
  user opted in to email and has an address on file.

Every attempt is recorded in ``NotificationLog`` with a status
(sent / failed / skipped) so the mobile ``/api/v1/me/notifications``
view can show a delivery history (planned for PR 5+).

The task is intentionally side-effect rich but pure-Python: it
returns a result dict rather than raising on failure, so the Q2
worker doesn't re-enqueue on a transient error from the push
provider. (Production retries will be added via the Q2 retry
config.)
"""
from __future__ import annotations

import json
import logging
from typing import Any

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from notifications.expo_client import (
    ExpoPushMessage,
    ExpoPushTicket,
    send_expo_push_notifications,
)
from notifications.models import NotificationLog
from players.models import User


logger = logging.getLogger(__name__)


def send_notification(
    user_id: int,
    event_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Send a notification (push + email) to a single user.

    Returns a result dict::

        {
            "push": "sent" | "skipped" | "failed",
            "email": "sent" | "skipped" | "failed",
            "errors": [str, ...],
        }

    The function never raises — every failure path returns a
    structured error so the Q2 worker treats the task as done.
    """
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return {
            "push": "skipped",
            "email": "skipped",
            "errors": [f"User {user_id} not found"],
        }

    result: dict[str, Any] = {
        "push": "skipped",
        "email": "skipped",
        "errors": [],
    }

    # ---- Push (Expo) ----
    if user.notify_push:
        if user.push_token:
            try:
                message = ExpoPushMessage(
                    to=user.push_token,
                    title=_event_title(event_type),
                    body=_event_body(event_type, payload),
                    data=payload,
                )
                tickets = send_expo_push_notifications([message])
                ticket: ExpoPushTicket | None = tickets[0] if tickets else None
                if ticket is not None and ticket.status == "ok":
                    result["push"] = "sent"
                    _log(
                        user,
                        event_type,
                        NotificationLog.Channel.PUSH,
                        NotificationLog.Status.SENT,
                    )
                else:
                    err = ticket.message if ticket is not None else "no ticket"
                    result["push"] = "failed"
                    result["errors"].append(f"push: {err}")
                    _log(
                        user,
                        event_type,
                        NotificationLog.Channel.PUSH,
                        NotificationLog.Status.FAILED,
                        err,
                    )
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Push dispatch failed for user %s", user_id)
                result["push"] = "failed"
                result["errors"].append(f"push: {exc}")
                _log(
                    user,
                    event_type,
                    NotificationLog.Channel.PUSH,
                    NotificationLog.Status.FAILED,
                    str(exc),
                )
        else:
            # Opted in but no token (probably a web client). Skip
            # but log so we can audit opt-in vs deliverability.
            result["push"] = "skipped"
            _log(
                user,
                event_type,
                NotificationLog.Channel.PUSH,
                NotificationLog.Status.SKIPPED,
                "no push_token",
            )

    # ---- Email (SMTP / Resend via Django's email backend) ----
    if user.notify_email:
        if user.email:
            try:
                subject = _event_title(event_type)
                body = _event_body(event_type, payload)
                send_mail(
                    subject=subject,
                    message=body,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                    fail_silently=False,
                )
                result["email"] = "sent"
                _log(
                    user,
                    event_type,
                    NotificationLog.Channel.EMAIL,
                    NotificationLog.Status.SENT,
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Email dispatch failed for user %s", user_id)
                result["email"] = "failed"
                result["errors"].append(f"email: {exc}")
                _log(
                    user,
                    event_type,
                    NotificationLog.Channel.EMAIL,
                    NotificationLog.Status.FAILED,
                    str(exc),
                )
        else:
            result["email"] = "skipped"
            _log(
                user,
                event_type,
                NotificationLog.Channel.EMAIL,
                NotificationLog.Status.SKIPPED,
                "no email",
            )

    return result


def _event_title(event_type: str) -> str:
    """Spanish titles for the three MVP events."""
    titles = {
        "match_created": "Nuevo partido disponible",
        "player_joined": "Un jugador se apuntó",
        "player_left": "Un jugador se bajó",
    }
    return titles.get(event_type, "Notificación")


def _event_body(event_type: str, payload: dict[str, Any]) -> str:
    """Render the body text from the payload for each event."""
    if event_type == "match_created":
        court = payload.get("court_name", "?")
        return f"Partido abierto en {court}"
    if event_type == "player_joined":
        name = payload.get("joining_user_name", "?")
        return f"{name} se apuntó al partido"
    if event_type == "player_left":
        name = payload.get("leaving_user_name", "?")
        return f"{name} se bajó del partido"
    return json.dumps(payload)


def _log(
    user: User,
    event_type: str,
    channel: str,
    status: str,
    error: str | None = None,
) -> None:
    """Insert a NotificationLog row for this attempt."""
    NotificationLog.objects.create(
        user=user,
        event_type=event_type,
        channel=channel,
        status=status,
        sent_at=timezone.now() if status == NotificationLog.Status.SENT else None,
        error=error or "",
    )