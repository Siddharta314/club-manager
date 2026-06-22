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

Level validation is mirrored at the serializer level so the API
returns 400 with a friendly message rather than relying on the
``LevelField`` validators to fire on ``full_clean()`` (which DRF
doesn't call by default for ``ModelSerializer.save``).
"""
from __future__ import annotations

from rest_framework import serializers

from .models import Companion


class CompanionSerializer(serializers.ModelSerializer):
    """Companion serializer with name and level."""

    class Meta:
        model = Companion
        fields = ["id", "match_id", "sponsored_by_id", "name", "level", "created_at"]
        read_only_fields = ["id", "match_id", "sponsored_by_id", "created_at"]

    def validate_name(self, value: str) -> str:
        if not value or not value.strip():
            raise serializers.ValidationError("Name must not be empty")
        return value.strip()

    def validate_level(self, value: float) -> float:
        # The LevelField validators on the model enforce 0.00–7.00;
        # we mirror the check here so the API returns 400 instead of
        # 500 on bad input.
        if value < 0.00 or value > 7.00:
            raise serializers.ValidationError("Level must be between 0.00 and 7.00")
        return value


class CompanionCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a Companion (name + level only).

    The ``match`` and ``sponsored_by`` fields are populated by the
    view from the URL and the request user respectively.
    """

    class Meta:
        model = Companion
        fields = ["name", "level"]

    def validate_name(self, value: str) -> str:
        if not value or not value.strip():
            raise serializers.ValidationError("Name must not be empty")
        return value.strip()

    def validate_level(self, value: float) -> float:
        if value < 0.00 or value > 7.00:
            raise serializers.ValidationError("Level must be between 0.00 and 7.00")
        return value
