"""Player profile serializers for the ``/me/`` endpoints.

Three serializers, one per endpoint shape:

- ``MeSerializer`` — read + write for ``GET/PATCH /api/v1/me/``.
  Exposes the fields a player can self-edit (name, level,
  notification flags) while keeping ``id``, ``email``, ``club``
  and ``role`` as read-only — role + club promotion happens
  through the admin endpoints, not through the player's own
  profile patch.
- ``PushTokenSerializer`` — body shape for
  ``PATCH /api/v1/me/push-token/``. Single ``push_token`` field,
  required, max 255 chars to match the model column.
- ``NotificationPreferencesSerializer`` — body shape for
  ``PATCH /api/v1/me/notifications/``. Exposes the two opt-in
  flags (``notify_push``, ``notify_email``) so the mobile client
  can render the toggle screen.
"""
from __future__ import annotations

from rest_framework import serializers

from players.models import User


class MeSerializer(serializers.ModelSerializer):
    """Serializer for ``GET/PATCH /api/v1/me/``.

    Read-only fields:

    - ``id`` — server-assigned.
    - ``email`` — Clerk manages this; out of scope for self-edit.
    - ``club`` — assigned via club onboarding (PR 5+).
    - ``role`` — promoted via admin endpoints, never by the
      player themselves.

    Editable fields: ``first_name``, ``last_name``, ``level``,
    ``notify_push``, ``notify_email``. Club admins can override a
    player's level via this endpoint too — the field is the same
    regardless of who is editing.
    """

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "level",
            "club",
            "role",
            "notify_push",
            "notify_email",
        ]
        read_only_fields = ["id", "email", "club", "role"]


class PushTokenSerializer(serializers.Serializer):
    """Serializer for ``PATCH /api/v1/me/push-token/``.

    Single field, ``allow_blank`` so empty string clears the Expo
    Push token. Max length mirrors the ``User.push_token`` column.
    We use a plain ``Serializer`` (not ``ModelSerializer``) because
    the endpoint only sets one column — there's no benefit to the
    auto-generated fields here.
    """

    push_token = serializers.CharField(max_length=255, allow_blank=True)


class NotificationPreferencesSerializer(serializers.ModelSerializer):
    """Serializer for ``PATCH /api/v1/me/notifications/``.

    Only the two opt-in flags are exposed; everything else stays
    unchanged so a client sending the same payload doesn't
    accidentally clobber unrelated columns.
    """

    class Meta:
        model = User
        fields = ["notify_push", "notify_email"]