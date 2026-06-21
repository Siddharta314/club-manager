"""match_slots app — eager auto-generated booking slots.

A `MatchSlot` is an empty bookable time range on a court. Slots are
generated eagerly from `clubs.Schedule` rules by
`match_slots.services.generate_slots()` (PR 2). This module owns the
data model only.

Uniqueness on `(court, start_time)` is the central invariant: regenerating
a schedule must not create duplicate slots. Eager generation works by
deleting future slots for the court and bulk-creating fresh ones in a
single transaction.

The reverse OneToOne to `matches.Match` is added in the matches PR
(commit 8) once that model exists.
"""
from django.db import models


class MatchSlot(models.Model):
    """A bookable time range on a court. One-to-one with the Match that
    eventually fills it (nullable until a player signs up)."""

    court = models.ForeignKey(
        "clubs.Court",
        on_delete=models.CASCADE,
        related_name="match_slots",
    )
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    is_active = models.BooleanField(
        default=True,
        help_text="Admins can disable a slot without deleting it.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "match_slots_matchslot"
        constraints = [
            models.UniqueConstraint(
                fields=["court", "start_time"],
                name="match_slots_court_start_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(end_time__gt=models.F("start_time")),
                name="match_slots_end_after_start",
            ),
        ]
        indexes = [
            models.Index(fields=["start_time"], name="match_slots_start_idx"),
            models.Index(fields=["court", "is_active"], name="match_slots_court_active_idx"),
        ]
        ordering = ("start_time",)

    def __str__(self):
        return f"{self.court} · {self.start_time:%Y-%m-%d %H:%M}"

    @property
    def is_future(self) -> bool:
        """True if this slot's start time is in the future."""
        from django.utils import timezone

        return self.start_time > timezone.now()

    @property
    def is_booked(self) -> bool:
        # The `match` reverse OneToOne is added in the matches PR (commit 8).
        return getattr(self, "match_id", None) is not None