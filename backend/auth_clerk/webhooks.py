"""Clerk webhook handlers with Svix signature verification.

Endpoint: ``POST /api/v1/auth/webhook/clerk/``

The endpoint is mounted by ``auth_clerk.urls`` and intentionally lives
outside DRF (the Svix library needs the raw request body, which DRF's
JSON parser would have already consumed).

Events
------
- ``user.created`` → create Django ``User`` (level=3.00, role='player',
  no club FK; all defaults from the model).
- ``user.updated`` → update email / name only — ``level``, ``club`` and
  ``role`` are domain state owned by Django and MUST NOT be overwritten
  by Clerk events.
- ``user.deleted`` → soft-delete the user (``is_active=False``),
  preserving FK relationships so historical matches and companions
  stay intact.

Each handler is idempotent: a duplicate ``user.created`` event is a
no-op (we use ``get_or_create`` semantics via the service layer).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from svix.webhooks import Webhook, WebhookVerificationError

from .services import apply_user_update, get_or_create_user_from_clerk, soft_delete_user

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Header names (Svix convention, lowercase per HTTP/2)
# ---------------------------------------------------------------------------
SVIX_HEADER_ID = "svix-id"
SVIX_HEADER_TIMESTAMP = "svix-timestamp"
SVIX_HEADER_SIGNATURE = "svix-signature"


# ---------------------------------------------------------------------------
# Public view
# ---------------------------------------------------------------------------
@csrf_exempt
@require_POST
def clerk_webhook(request: HttpRequest) -> JsonResponse:
    """Receive and dispatch a Svix-signed Clerk event.

    Returns:
        200 OK on successful dispatch (including duplicate events).
        400 Bad Request if the body is not valid JSON.
        401 Unauthorized if Svix signature verification fails.
    """
    if not settings.CLERK_WEBHOOK_SECRET:
        logger.error("CLERK_WEBHOOK_SECRET not configured — refusing webhook")
        return JsonResponse({"detail": "Webhook secret not configured"}, status=500)

    try:
        payload = _verify_and_parse(request)
    except WebhookVerificationError as exc:
        logger.warning("Svix verification failed: %s", exc)
        return JsonResponse({"detail": "Invalid signature"}, status=401)
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)

    event_type = payload.get("type", "")
    data = payload.get("data", {}) or {}
    dispatcher = _DISPATCH.get(event_type)
    if dispatcher is None:
        # Clerk may add new event types we don't care about; ack so they
        # don't retry forever.
        logger.info("Ignoring Clerk event type=%s", event_type)
        return JsonResponse({"detail": "Ignored"}, status=200)

    try:
        dispatcher(data)
    except Exception:  # noqa: BLE001 — surface as 500 so Clerk retries
        logger.exception("Handler failed for event=%s", event_type)
        return JsonResponse({"detail": "Handler error"}, status=500)

    return JsonResponse({"detail": "ok"}, status=200)


# ---------------------------------------------------------------------------
# Event handlers (typed)
# ---------------------------------------------------------------------------
def _handle_user_created(data: dict[str, Any]) -> None:
    clerk_user_id = _require_clerk_id(data)
    email = _first_email(data)
    name = _extract_name_from_data(data)
    user, created = get_or_create_user_from_clerk(
        clerk_user_id=clerk_user_id,
        email=email,
        name=name,
    )
    logger.info("user.created clerk_id=%s created=%s", clerk_user_id, created)
    # Defensive: if the user already existed (e.g. duplicate event),
    # still apply profile fields so the mirror stays in sync.
    if not created:
        apply_user_update(user, data)


def _handle_user_updated(data: dict[str, Any]) -> None:
    clerk_user_id = _require_clerk_id(data)
    from django.contrib.auth import get_user_model

    User = get_user_model()
    try:
        user = User.objects.get(clerk_user_id=clerk_user_id)
    except User.DoesNotExist:
        # Update before create is unusual, but if Clerk sends an update
        # for an unknown user we materialise it so we don't drop data.
        user, _ = get_or_create_user_from_clerk(
            clerk_user_id=clerk_user_id,
            email=_first_email(data),
            name=_extract_name_from_data(data),
        )
        return
    apply_user_update(user, data)
    logger.info("user.updated clerk_id=%s", clerk_user_id)


def _handle_user_deleted(data: dict[str, Any]) -> None:
    clerk_user_id = _require_clerk_id(data)
    from django.contrib.auth import get_user_model

    User = get_user_model()
    try:
        user = User.objects.get(clerk_user_id=clerk_user_id)
    except User.DoesNotExist:
        logger.info("user.deleted for unknown clerk_id=%s (no-op)", clerk_user_id)
        return
    soft_delete_user(user)
    logger.info("user.deleted clerk_id=%s soft_deleted=True", clerk_user_id)


_DISPATCH: dict[str, Any] = {
    "user.created": _handle_user_created,
    "user.updated": _handle_user_updated,
    "user.deleted": _handle_user_deleted,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _verify_and_parse(request: HttpRequest) -> dict[str, Any]:
    """Run Svix verification and JSON-parse the payload.

    Svix expects the raw bytes — reading ``request.body`` here is
    intentional, before any DRF parser could touch it.
    """
    headers = {
        SVIX_HEADER_ID: request.headers.get(SVIX_HEADER_ID, ""),
        SVIX_HEADER_TIMESTAMP: request.headers.get(SVIX_HEADER_TIMESTAMP, ""),
        SVIX_HEADER_SIGNATURE: request.headers.get(SVIX_HEADER_SIGNATURE, ""),
    }
    wh = Webhook(settings.CLERK_WEBHOOK_SECRET)
    # Svix returns the parsed dict; raise on bad signature.
    payload = wh.verify(request.body, headers)
    return payload if isinstance(payload, dict) else {}


def _require_clerk_id(data: dict[str, Any]) -> str:
    cid = data.get("id") or data.get("user_id")
    if not cid:
        raise ValueError("Clerk event missing user id")
    return str(cid)


def _first_email(data: dict[str, Any]) -> str:
    """Clerk payloads list email_addresses as objects with ``id`` /
    ``email_address``. Pull the first ``email_address`` we find."""
    emails = data.get("email_addresses") or []
    for entry in emails:
        addr = entry.get("email_address") if isinstance(entry, dict) else None
        if addr:
            return str(addr)
    primary = data.get("primary_email_address_id")
    if primary and isinstance(emails, list):
        for entry in emails:
            if isinstance(entry, dict) and entry.get("id") == primary:
                addr = entry.get("email_address")
                if addr:
                    return str(addr)
    return str(data.get("email_address") or "")


def _extract_name_from_data(data: dict[str, Any]) -> str:
    first = (data.get("first_name") or "").strip()
    last = (data.get("last_name") or "").strip()
    username = (data.get("username") or "").strip()
    if username:
        return username
    full = f"{first} {last}".strip()
    return full
