"""matches app — Match and MatchPlayer models.

A `Match` is the booking that fills a `MatchSlot`. Lifecycle is derived
from the slot's start/end time and the host/players collection; we don't
persist status flags to keep state from drifting. Status helpers live as
properties below — the lifecycle (host-first, level matching, capacity)
itself is owned by `matches.services` (PR 3).

`MatchPlayer` represents a signed-up user on a Match. The host is the
first MatchPlayer added; uniqueness on (match, user) prevents duplicate
signups. is_host is computed from the related `host` FK on Match rather
than stored as a separate flag.
"""
from decimal import Decimal

from django.conf import settings
from django.db import models

from players.fields import LevelField


class Match(models.Model):
    """A 2v2 booking that fills a MatchSlot.

    The OneToOne lives on the MatchSlot side (`MatchSlot.booked_match`) so
    the slot can be created empty and booked later without gymnastics. This
    model exposes `slot` as a property that reads through that relation.
    """

    host = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="matches_hosted",
    )
    level_min = LevelField(default=Decimal("2.75"))
    level_max = LevelField(default=Decimal("4.25"))
    is_cancelled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "matches_match"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(level_max__gt=models.F("level_min")),
                name="matches_match_level_range_invariant",
            ),
        ]
        indexes = [
            models.Index(fields=["host"], name="matches_match_host_idx"),
            models.Index(fields=["is_cancelled"], name="matches_match_cancelled_idx"),
        ]
        ordering = ("-created_at",)

    def __str__(self):
        slot = getattr(self, "match_slot", None)
        return f"Match<{self.pk}> on {slot}" if slot else f"Match<{self.pk}>"

    @property
    def slot(self):
        """The slot this match fills (read-through to MatchSlot.booked_match)."""
        try:
            return self.match_slot
        except MatchSlot.DoesNotExist:
            return None

    # ----- Derived lifecycle properties (PR 1 — flags only; PR 3 wires state) -----
    @property
    def is_open(self) -> bool:
        """True when the match accepts new signups."""
        return not self.is_cancelled

    @property
    def is_full(self) -> bool:
        """True when 4 participants (players + companions) have signed up."""
        return self.participant_count() >= 4

    @property
    def is_in_progress(self) -> bool:
        from django.utils import timezone

        slot = self.slot
        if slot is None:
            return False
        now = timezone.now()
        return not self.is_cancelled and slot.start_time <= now < slot.end_time

    @property
    def is_finished(self) -> bool:
        from django.utils import timezone

        slot = self.slot
        if slot is None:
            return False
        return not self.is_cancelled and timezone.now() >= slot.end_time

    def participant_count(self) -> int:
        """Players + companions counts toward the 4-cap."""
        players = self.players.count()
        # Companion reverse relation is added in the companions PR (commit 9).
        # We tolerate its absence so commit 8 stays self-contained.
        companions = 0
        if hasattr(self, "companions"):
            try:
                companions = self.companions.count()
            except Exception:  # pragma: no cover - relation unresolved
                companions = 0
        return players + companions


class MatchPlayer(models.Model):
    """A signed-up user on a Match. The host is the first MatchPlayer added."""

    match = models.ForeignKey(
        Match,
        on_delete=models.CASCADE,
        related_name="players",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="match_signups",
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "matches_matchplayer"
        constraints = [
            models.UniqueConstraint(
                fields=["match", "user"],
                name="matches_matchplayer_match_user_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["user"], name="matches_matchplayer_user_idx"),
        ]
        ordering = ("joined_at",)

    def __str__(self):
        return f"{self.user} @ {self.match}"

    @property
    def is_host(self) -> bool:
        return self.user_id == self.match.host_id