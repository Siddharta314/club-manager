"""Clubs app — Club, Court, Schedule models.

Domain notes
------------
- `Club.address` is REQUIRED (per spec). The uniqueness check on
  ``(name, address)`` prevents accidental duplicate clubs from the
  self-service onboarding flow.
- `Club.admins` is the M2M relation that gates the IsClubAdmin
  permission: a user can manage a club iff they are in this set. The
  creator is auto-added via ``ClubViewSet.perform_create`` so legacy
  ``created_by`` semantics continue to work; ``created_by`` is kept
  for audit (who originally signed the club into existence).
- `Court` belongs to a `Club` (a club has N courts). `is_active` toggles
  visibility for booking.
- `Schedule` declares the weekly availability for a court: weekday (0=Mon
  – 6=Sun), start_time, end_time, duration_minutes. Eager slot generation
  is handled by `match_slots.services.generate_slots()` (PR 2) — this model
  just stores the rules.
- The `User.club` reverse relation is wired via `related_name="members"`,
  but the forward FK is added in the players PR (commit 6 — same as this
  one — via a follow-up migration). See `players/models.User`.
"""
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Club(models.Model):
    """A padel club. Self-service created by any Clerk user."""

    name = models.CharField(max_length=120)
    address = models.CharField(
        max_length=255,
        help_text="Required physical address — used for uniqueness checks.",
    )
    photo = models.ImageField(upload_to="clubs/", blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="clubs_created",
        help_text="Original creator; kept for audit. Use ``admins`` for access control.",
    )
    admins = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="administered_clubs",
        help_text="Users who can manage this club (CRUD courts/schedules, slots).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "clubs_club"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["name", "address"],
                name="clubs_club_name_address_uniq",
            ),
            models.CheckConstraint(
                condition=~models.Q(address=""),
                name="clubs_club_address_required",
            ),
        ]
        indexes = [
            models.Index(fields=["name"], name="clubs_club_name_idx"),
        ]

    def __str__(self):
        return self.name

    def is_admin(self, user: "models.Model | int | None") -> bool:
        """Return True if ``user`` can manage this club.

        ``user`` may be a User instance, a user pk, or ``None`` (returns
        ``False``). Used by ``IsClubAdmin`` and the admin endpoints to
        avoid duplicating the membership check.
        """
        if user is None:
            return False
        user_id = user if isinstance(user, int) else getattr(user, "pk", None)
        if user_id is None:
            return False
        return self.admins.filter(pk=user_id).exists()


class Court(models.Model):
    """A physical court belonging to a club."""

    club = models.ForeignKey(
        Club,
        on_delete=models.CASCADE,
        related_name="courts",
    )
    name = models.CharField(max_length=80)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "clubs_court"
        constraints = [
            models.UniqueConstraint(
                fields=["club", "name"],
                name="clubs_court_club_name_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["club", "is_active"], name="clubs_court_club_active_idx"),
        ]

    def __str__(self):
        return f"{self.club.name} – {self.name}"


class Schedule(models.Model):
    """Weekly availability rule for a single court.

    The match_slots service (PR 2) reads these rules and generates
    `MatchSlot` rows transactionally when a Schedule is saved or updated.
    """

    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

    court = models.ForeignKey(
        Court,
        on_delete=models.CASCADE,
        related_name="schedules",
    )
    weekday = models.IntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    duration_minutes = models.PositiveIntegerField(
        validators=[MinValueValidator(15)],
        help_text="Slot duration in minutes; must be >= 15.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "clubs_schedule"
        indexes = [
            models.Index(fields=["court", "weekday"], name="clubs_schedule_court_wd_idx"),
        ]

    def __str__(self):
        return f"{self.court} · {self.get_weekday_display()} {self.start_time:%H:%M}–{self.end_time:%H:%M}"