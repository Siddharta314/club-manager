"""Companions app — anonymous, per-match, volatile players.

A `Companion` is an anonymous (named + level only) participant sponsored
by a signed-up user on a Match. Companions count toward the 4-cap along
with `MatchPlayer`s, are visible to match participants, and cascade-delete
with their parent Match.

Domain notes
------------
- `sponsored_by` is the signed-up user who registered the companion. The
  companion's chat messages (PR 4) attribute to `author_companion`.
- `level` is a `LevelField` so the same domain rules apply as for players.
- Cascade-delete from Match: companions vanish with the match.
"""
from django.conf import settings
from django.db import models

from players.fields import LevelField


class Companion(models.Model):
    """Anonymous player on a Match, sponsored by a signed-up user."""

    match = models.ForeignKey(
        "matches.Match",
        on_delete=models.CASCADE,
        related_name="companions",
    )
    sponsored_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="companions_sponsored",
    )
    name = models.CharField(max_length=80)
    level = LevelField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "companions_companion"
        indexes = [
            models.Index(fields=["match"], name="companions_match_idx"),
            models.Index(fields=["sponsored_by"], name="companions_sponsor_idx"),
        ]
        ordering = ("created_at",)

    def __str__(self):
        return f"{self.name} ({self.level}) @ {self.match}"