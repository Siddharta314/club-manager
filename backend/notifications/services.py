"""Notification dispatch service.

Enqueues per-user Q2 tasks for the three notification triggers the
spec calls out:

- ``enqueue_match_created(match_id)`` — fan-out to subscribed
  members of the club (excluding the host).
- ``enqueue_player_joined(match_id, joining_user_id)`` — fan-out to
  every other player on the match.
- ``enqueue_player_left(match_id, leaving_user_id)`` — same, on
  leave.

Each enqueue is a thin DB read + N ``send_notification.delay(...)``
calls. The actual push / email dispatch lives in
``notifications.tasks.send_notification``, which is what runs in
the Q2 worker process.

User opt-in checks (``User.notify_push``, ``User.notify_email``,
``User.push_token`` presence) happen **inside the task**, not here,
so enqueueing is a cheap read and the per-user decision is logged
via ``NotificationLog``.
"""
from __future__ import annotations

from typing import Any

from django.db.models import Q

from companions.models import Companion
from matches.models import Match, MatchPlayer
from players.models import User


def _match_other_user_ids(match: Match, exclude_user_id: int) -> list[int]:
    """Return user IDs of all MatchPlayers in this match except ``exclude_user_id``."""
    return list(
        MatchPlayer.objects.filter(match=match)
        .exclude(user_id=exclude_user_id)
        .values_list("user_id", flat=True)
    )


def enqueue_match_created(match_id: int) -> None:
    """Notify subscribed players of the club that a new match was created.

    Scope: all users with ``User.club == this club`` and
    ``notify_push or notify_email = True``. The host is excluded so
    they don't get a "new match" notification about their own match.

    Each recipient is queued as an independent Q2 task so a slow
    push or email provider for one user doesn't block the rest.
    """
    match = Match.objects.select_related(
        "match_slot__court__club"
    ).get(pk=match_id)
    club = match.match_slot.court.club

    targets = (
        User.objects.filter(club=club)
        .exclude(pk=match.host_id)
        .filter(Q(notify_push=True) | Q(notify_email=True))
    )

    payload: dict[str, Any] = {
        "match_id": match.pk,
        "club_id": club.pk,
        "start_time": match.match_slot.start_time.isoformat(),
        "court_name": match.match_slot.court.name,
    }
    # Lazy import to keep this module importable without the Q2
    # task being on disk (so commit ordering stays clean: services
    # can land before tasks).
    from notifications.tasks import send_notification

    for user in targets:
        send_notification.delay(
            user_id=user.pk,
            event_type="match_created",
            payload=payload,
        )


def enqueue_player_joined(match_id: int, joining_user_id: int) -> None:
    """Notify the other players on the match that someone joined."""
    match = Match.objects.select_related(
        "match_slot__court__club"
    ).get(pk=match_id)
    other_user_ids = _match_other_user_ids(match, joining_user_id)
    joining_user = User.objects.get(pk=joining_user_id)
    payload: dict[str, Any] = {
        "match_id": match.pk,
        "joining_user_id": joining_user_id,
        "joining_user_name": (
            joining_user.get_full_name() or joining_user.email or ""
        ),
    }
    from notifications.tasks import send_notification

    for uid in other_user_ids:
        send_notification.delay(
            user_id=uid,
            event_type="player_joined",
            payload=payload,
        )


def enqueue_player_left(match_id: int, leaving_user_id: int) -> None:
    """Notify the remaining players on the match that someone left."""
    match = Match.objects.select_related(
        "match_slot__court__club"
    ).get(pk=match_id)
    other_user_ids = _match_other_user_ids(match, leaving_user_id)
    leaving_user = User.objects.get(pk=leaving_user_id)
    payload: dict[str, Any] = {
        "match_id": match.pk,
        "leaving_user_id": leaving_user_id,
        "leaving_user_name": (
            leaving_user.get_full_name() or leaving_user.email or ""
        ),
    }
    from notifications.tasks import send_notification

    for uid in other_user_ids:
        send_notification.delay(
            user_id=uid,
            event_type="player_left",
            payload=payload,
        )