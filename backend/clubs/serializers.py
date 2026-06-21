"""DRF serializers for the clubs app.

Three concerns:

- ``ClubSerializer`` — read shape, nests ``CourtSerializer`` so the
  mobile client gets the club's courts in one round trip.
- ``ClubWriteSerializer`` — write shape with explicit
  ``address != ""`` validation that mirrors the model's
  ``CheckConstraint``. We surface a friendlier ``ValidationError``
  instead of an IntegrityError so the API returns 400 with a clear
  message.
- ``ScheduleSerializer`` — adds the time / duration invariants from
  the design (``end_time > start_time``, ``duration_minutes > 0``
  and ``<= 240``).

Photo URLs go through ``request.build_absolute_uri`` so the mobile
client always gets a full URL (relative paths break in production).
"""
from __future__ import annotations

from typing import Any

from rest_framework import serializers

from .models import Club, Court, Schedule


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class AbsoluteURLField(serializers.ImageField):
    """ImageField that returns an absolute URL.

    DRF's stock ImageField renders ``<MEDIA_URL>/<upload_to>/<name>``
    which is a relative path. The mobile client needs an absolute
    URL to render the image without a proxy. We override
    ``to_representation`` to call ``request.build_absolute_uri`` when
    a request is bound to the serializer context.
    """

    def to_representation(self, value: Any) -> str | None:
        if not value:
            return None
        url: str = super().to_representation(value)
        request = self.context.get("request")
        if request is not None:
            return request.build_absolute_uri(url)
        return url


# ---------------------------------------------------------------------------
# Club
# ---------------------------------------------------------------------------
class ClubSerializer(serializers.ModelSerializer):
    """Read shape — includes nested courts for one-round-trip fetch."""

    photo = AbsoluteURLField(read_only=True)
    courts = serializers.SerializerMethodField()
    created_by = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Club
        fields = (
            "id",
            "name",
            "address",
            "photo",
            "created_by",
            "created_at",
            "updated_at",
            "courts",
        )

    def get_courts(self, obj: Club) -> list[dict[str, Any]]:
        # Prefetched in the view when present; fallback to a single query.
        courts = list(obj.courts.all())
        return CourtSerializer(courts, many=True, context=self.context).data


class ClubWriteSerializer(serializers.ModelSerializer):
    """Write shape — enforces address != '' and ignores photo URL."""

    photo = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = Club
        fields = ("id", "name", "address", "photo")

    def validate_address(self, value: str) -> str:
        # The model has a CheckConstraint on address != ''; we mirror
        # the rule here so the API returns 400 instead of 500 on bad
        # input.
        if not value or not value.strip():
            raise serializers.ValidationError("Address is required.")
        return value.strip()

    def validate_name(self, value: str) -> str:
        if not value or not value.strip():
            raise serializers.ValidationError("Name is required.")
        return value.strip()


# ---------------------------------------------------------------------------
# Court
# ---------------------------------------------------------------------------
class CourtSerializer(serializers.ModelSerializer):
    """Court read/write shape — name + is_active + club FK (write only)."""

    class Meta:
        model = Court
        fields = ("id", "club", "name", "is_active", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")

    def validate_name(self, value: str) -> str:
        if not value or not value.strip():
            raise serializers.ValidationError("Name is required.")
        return value.strip()


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------
class ScheduleSerializer(serializers.ModelSerializer):
    """Schedule read/write — enforces time / duration invariants."""

    MAX_DURATION_MINUTES: int = 240  # 4 hours per slot rule

    class Meta:
        model = Schedule
        fields = (
            "id",
            "court",
            "weekday",
            "start_time",
            "end_time",
            "duration_minutes",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        start = attrs.get("start_time")
        end = attrs.get("end_time")
        duration = attrs.get("duration_minutes")
        # Use the persisted values for partial updates.
        if self.instance is not None:
            start = start or self.instance.start_time
            end = end or self.instance.end_time
            duration = duration or self.instance.duration_minutes
        if start is not None and end is not None and end <= start:
            raise serializers.ValidationError(
                {"end_time": "End time must be after start time."}
            )
        if duration is not None:
            if duration <= 0:
                raise serializers.ValidationError(
                    {"duration_minutes": "Duration must be greater than 0."}
                )
            if duration > self.MAX_DURATION_MINUTES:
                raise serializers.ValidationError(
                    {
                        "duration_minutes": (
                            f"Duration must be {self.MAX_DURATION_MINUTES} minutes or less."
                        )
                    }
                )
        return attrs
