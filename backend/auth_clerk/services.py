"""Service-layer helpers for the auth_clerk app.

Pure-Python functions that the middleware, webhooks, and management
command all share. Keeping them in one module avoids circular imports
between middleware.py and webhooks.py.
"""
from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model

User = get_user_model()


def get_or_create_user_from_clerk(
    clerk_user_id: str,
    email: str,
    name: str,
) -> tuple[Any, bool]:
    """Look up the Django user by Clerk ID, creating it on first sight.

    Returns a ``(user, created)`` tuple mirroring Django's
    ``User.objects.get_or_create`` semantics. New users default to
    ``level=3.00`` (set by the model default), ``role='player'`` and
    no club FK — those are the spec's requirements for ``user.created``.

    Type hints: ``name`` is the best-effort full name from Clerk. We
    fall back to ``email`` if it's empty so the ``username`` field (which
    is ``NOT NULL`` in ``AbstractUser``) is never blank.
    """
    defaults: dict[str, Any] = {
        "email": email or "",
        "username": name or email or clerk_user_id,
    }
    user, created = User.objects.get_or_create(
        clerk_user_id=clerk_user_id,
        defaults=defaults,
    )
    if created and not user.username:
        user.username = defaults["username"]
        user.save(update_fields=["username"])
    return user, created


def apply_user_update(user: Any, payload: dict[str, Any]) -> None:
    """Apply a ``user.updated`` payload to ``user``.

    Per spec: only email / name / photo may change. ``level``, ``club``,
    ``role`` are domain state owned by Django and must NOT be touched
    by Clerk webhooks.

    Args:
        user: the Django user instance (must already be persisted).
        payload: the ``data`` field of the Clerk event.
    """
    fields_to_update: list[str] = []

    # Email: Clerk payloads carry ``email_addresses`` (an array of
    # {id, email_address}); some templates also expose a flat ``email``.
    # We extract via the same helper the webhook uses so the contract
    # stays in one place.
    new_email = _extract_email(payload)
    if new_email and new_email != user.email:
        user.email = new_email
        fields_to_update.append("email")

    new_username = _extract_username(payload)
    if new_username and new_username != user.username:
        user.username = new_username
        fields_to_update.append("username")

    image_url = payload.get("image_url") or payload.get("profile_image_url")
    if image_url is not None and image_url != getattr(user, "avatar_url", None):
        # We don't store a Clerk image on User (avatars live in players
        # app per design). This branch is here so future fields can be
        # added without changing the contract.
        pass

    if fields_to_update:
        user.save(update_fields=fields_to_update)


def _extract_email(payload: dict[str, Any]) -> str:
    """Pull the primary email address from a Clerk payload."""
    flat = payload.get("email_address") or payload.get("email")
    if flat:
        return str(flat)
    emails = payload.get("email_addresses") or []
    primary_id = payload.get("primary_email_address_id")
    for entry in emails:
        if not isinstance(entry, dict):
            continue
        if primary_id and entry.get("id") != primary_id:
            continue
        addr = entry.get("email_address")
        if addr:
            return str(addr)
    # Fallback: first entry with an address.
    for entry in emails:
        if isinstance(entry, dict) and entry.get("email_address"):
            return str(entry["email_address"])
    return ""


def _extract_username(payload: dict[str, Any]) -> str:
    """Pull a human-readable username from a Clerk payload.

    Preference order: ``username`` → ``"first_name last_name"``.
    Empty values are ignored.
    """
    username = (payload.get("username") or "").strip()
    if username:
        return username
    first = (payload.get("first_name") or "").strip()
    last = (payload.get("last_name") or "").strip()
    return f"{first} {last}".strip()


def soft_delete_user(user: Any) -> None:
    """Mark a user as inactive without deleting the row.

    Preserves FK relationships (matches, companions, etc.) per spec:
    "user.deleted soft-deletes (is_active=false), preserving FKs."
    """
    if user.is_active:
        user.is_active = False
        user.save(update_fields=["is_active"])
