"""match_slots app — DRF serializers.

The shape we expose to the mobile client is intentionally thin: id,
court name, start/end times, and the booking status flag. We don't
leak internal IDs like ``booked_match_id`` — those are for backend
join logic only.
"""
from __future__ import annotations

from rest_framework import serializers

from .models import MatchSlot


class MatchSlotSerializer(serializers.ModelSerializer):
    """Read-only shape for the mobile client's slot listing."""

    court_name = serializers.CharField(source="court.name", read_only=True)
    court_id = serializers.IntegerField(source="court.id", read_only=True)
    is_booked = serializers.BooleanField(read_only=True)

    class Meta:
        model = MatchSlot
        fields = (
            "id",
            "court",
            "court_id",
            "court_name",
            "start_time",
            "end_time",
            "is_active",
            "is_booked",
        )
        read_only_fields = fields
