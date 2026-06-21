"""Players app — User model and LevelField.

This module owns the custom `User` model referenced by `AUTH_USER_MODEL`
plus the centesimal `LevelField` used by User (and re-exported for reuse in
matches / companions via `players.fields.LevelField`).

Domain notes
------------
- `clerk_user_id` is the source-of-truth identifier from Clerk. It is
  immutable once set so webhooks can rely on it.
- `level` defaults to 3.00 — every new player self-reports at 3.00 unless
  `club_admin` overrides it.
- The `club` ForeignKey is added in the clubs PR (commit 6) since the FK
  target `clubs.Club` must exist for Django to resolve it. We document that
  here so callers know the relationship is intentional.
- `push_token` is set by the Expo client via `PATCH /api/v1/me/push-token/`
  (wired in PR 4).
- `notify_push` / `notify_email` default to True; players opt out via
  `PATCH /api/v1/me/notifications/`.
"""
from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.db import models

from .fields import LevelField


class User(AbstractUser):
    """Custom user model — Clerk-backed, club-bound (clubs PR), level-aware."""

    class Role(models.TextChoices):
        PLAYER = "player", "Player"
        CLUB_ADMIN = "club_admin", "Club admin"
        SUPER_ADMIN = "super_admin", "Super admin"

    clerk_user_id = models.CharField(
        max_length=64,
        unique=True,
        blank=True,
        null=True,
        help_text="Stable Clerk user identifier (immutable post-creation).",
    )
    level = LevelField(default=Decimal("3.00"))
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.PLAYER,
    )
    push_token = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Expo push token registered by the mobile client.",
    )
    notify_push = models.BooleanField(
        default=True,
        help_text="Opt-in flag for Expo Push notifications.",
    )
    notify_email = models.BooleanField(
        default=True,
        help_text="Opt-in flag for Resend email notifications.",
    )

    class Meta:
        db_table = "players_user"
        indexes = [
            models.Index(fields=["clerk_user_id"], name="players_user_clerk_idx"),
        ]

    def __str__(self):
        return self.username or self.email or f"User<{self.pk}>"

    @property
    def is_club_admin(self) -> bool:
        return self.role == self.Role.CLUB_ADMIN

    @property
    def is_super_admin(self) -> bool:
        return self.role == self.Role.SUPER_ADMIN