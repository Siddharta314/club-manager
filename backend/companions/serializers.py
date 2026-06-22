"""DRF serializers for the companions app.

Two serializers:

- ``CompanionSerializer`` — full read shape used for the
  ``/api/v1/matches/{id}/companions/`` response and the
  ``MatchSerializer.companions`` nested list. The match and sponsor
  FKs are read-only — they're set by the view, not the request body.
- ``CompanionCreateSerializer`` — thin write shape for the same
  endpoint. We keep a separate class so the read shape can grow
  fields (audit metadata, etc.) without forcing a breaking change
  on the create payload.

Both serializers share the same ``name`` and ``level`` validators —
``validate_companion_name`` and ``validate_companion_level``. The
validators mirror the ``LevelField`` bounds (0.00–7.00) so the API
returns 400 with a friendly message rather than relying on
``full_clean()`` (which DRF doesn't call by default for
``ModelSerializer.save``).
"""
from __future__ import annotations

from rest_framework import serializers

from .models import Companion


def validate_companion_name(value: str) -> str:
    """Reject empty / whitespace-only companion names; return the trimmed value.

    Shared between ``CompanionSerializer`` and ``CompanionCreateSerializer``
    so the rules live in exactly one place.
    """
    if not value or not value.strip():
        raise serializers.ValidationError("Name must not be empty")
    return value.strip()


def validate_companion_level(value: float) -> float:
    """Coerce ``value`` to ``float`` and enforce the 0.00–7.00 range.

    The ``LevelField`` validators on the model also enforce the same
    bounds at ``full_clean()`` time, but DRF does not call ``full_clean``
    on ``save`` by default — so we mirror the check here to return a
    clean 400 instead of a 500 on bad input.
    """
    try:
        level = float(value)
    except (TypeError, ValueError) as exc:
        raise serializers.ValidationError("Level must be a number") from exc
    if level < 0.00 or level > 7.00:
        raise serializers.ValidationError("Level must be between 0.00 and 7.00")
    return level


class CompanionSerializer(serializers.ModelSerializer):
    """Companion serializer (read + write shape)."""

    class Meta:
        model = Companion
        fields = ["id", "match_id", "sponsored_by_id", "name", "level", "created_at"]
        read_only_fields = ["id", "match_id", "sponsored_by_id", "created_at"]

    def validate_name(self, value: str) -> str:
        return validate_companion_name(value)

    def validate_level(self, value: float) -> float:
        return validate_companion_level(value)


class CompanionCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a Companion (name + level only).

    The ``match`` and ``sponsored_by`` fields are populated by the
    view from the URL and the request user respectively.
    """

    class Meta:
        model = Companion
        fields = ["name", "level"]

    def validate_name(self, value: str) -> str:
        return validate_companion_name(value)

    def validate_level(self, value: float) -> float:
        return validate_companion_level(value)