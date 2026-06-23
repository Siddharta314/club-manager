"""DRF serializers for the matches app.

Three serializers:

- ``MatchPlayerSerializer`` — read-only projection of a MatchPlayer for
  the match detail endpoint. Includes the host flag so the mobile
  client can render the host badge without a second round trip.
- ``MatchSerializer`` — full match read shape, nesting players and
  companions and exposing a ``capacity`` summary block computed by
  ``matches.services.get_capacity_status``.
- ``JoinMatchRequestSerializer`` — placeholder for the join body. The
  MVP has no per-join options, but keeping the shape means we can
  extend it (e.g. "bring companion" payload) without a breaking
  client change.

Type hints throughout; explicit field-level accessors so the
``source="user.pk"`` indirection is type-safe in IDEs.
"""
from __future__ import annotations

from rest_framework import serializers

from clubs.models import Court

from .models import Match, MatchPlayer


class CourtBriefSerializer(serializers.ModelSerializer):
    """Read-only projection of a ``Court`` for nested use on ``MatchSerializer``.

    Per design §1 (mobile-match-browse-signup), the ``MatchListView`` response
    needs a ``court: { id, name }`` block so the mobile ``MatchCard`` can
    render the court name without a separate round trip per match. Keeps the
    field list tight (id + name only) to avoid leaking unrelated court
    metadata into the match payload.
    """

    class Meta:
        model = Court
        fields = ("id", "name")


class MatchPlayerSerializer(serializers.ModelSerializer):
    """Read-only serializer for a player in a match."""

    user_id = serializers.IntegerField(source="user.pk", read_only=True)
    user_name = serializers.CharField(source="user.get_full_name", read_only=True)
    user_level = serializers.DecimalField(
        source="user.level",
        max_digits=4,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = MatchPlayer
        fields = ["user_id", "user_name", "user_level", "joined_at", "is_host"]


class MatchSerializer(serializers.ModelSerializer):
    """Match read shape — full detail for the mobile client."""

    players = MatchPlayerSerializer(many=True, read_only=True)
    companions = serializers.SerializerMethodField()
    court_id = serializers.IntegerField(source="slot.court_id", read_only=True)
    court = CourtBriefSerializer(read_only=True)
    start_time = serializers.DateTimeField(source="slot.start_time", read_only=True)
    end_time = serializers.DateTimeField(source="slot.end_time", read_only=True)
    capacity = serializers.SerializerMethodField()

    class Meta:
        model = Match
        fields = [
            "id",
            "court_id",
            "court",
            "start_time",
            "end_time",
            "level_min",
            "level_max",
            "is_cancelled",
            "players",
            "companions",
            "capacity",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "level_min",
            "level_max",
            "is_cancelled",
            "created_at",
        ]

    def get_companions(self, obj: Match) -> list[dict]:
        """Return a stable, ordered companion list.

        We resolve the lazy ``companions`` reverse relation (added by
        the companions app) and serialise each row via the
        CompanionSerializer. Prefetched in the view when available.
        """
        # Local import to avoid loading the companions app at import
        # time; the import is harmless because the app is in
        # INSTALLED_APPS, but it keeps the dependency graph explicit.
        from companions.serializers import CompanionSerializer

        companions = list(obj.companions.all().order_by("created_at"))
        return CompanionSerializer(companions, many=True, context=self.context).data

    def get_capacity(self, obj: Match) -> dict:
        """Compute a capacity snapshot via the service layer.

        Using a service call here keeps the wire shape consistent
        with what other views (e.g. a future match-list endpoint)
        will expose, and concentrates the count logic in one place.
        """
        # Local import for the same reason as above.
        from .services import get_capacity_status

        status = get_capacity_status(obj)
        return {
            "player_count": status.player_count,
            "companion_count": status.companion_count,
            "total": status.total,
            "is_full": status.is_full,
            "is_open": status.is_open,
            "is_in_progress": status.is_in_progress,
            "is_finished": status.is_finished,
        }


class JoinMatchRequestSerializer(serializers.Serializer):
    """Empty for now; placeholder for future options (e.g., bring companion)."""

    pass
