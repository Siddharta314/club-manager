"""Match lifecycle and capacity business logic.

A Match is created from an empty MatchSlot when the first player joins.
The first joiner becomes the host. Match level range = host.level ± 0.25.
Subsequent joins are accepted if joiner.level ∈ [level_min, level_max].
Admins can add any player regardless of range (override).
Capacity is 4 (MatchPlayer + Companion combined).
Leaving from full reverts state to active.

Pure functions / dataclasses — no Django request/response objects here
so the module is testable in isolation. Views are thin shells that call
into this layer and translate ``ValueError`` to 400 responses.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from match_slots.models import MatchSlot

from .models import Match, MatchPlayer


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class LevelRange:
    """Half-open inclusive level window.

    Spec: range = host.level ± 0.25. We use inclusive bounds on both
    sides so a joiner at the exact min/max is accepted; that matches
    the typical padel bracket semantics.
    """

    min: float
    max: float

    @classmethod
    def from_host(cls, host_level: Decimal | float) -> LevelRange:
        """Build a range from a host's level (±0.25)."""
        base = float(host_level)
        return cls(min=base - 0.25, max=base + 0.25)

    def contains(self, level: Decimal | float) -> bool:
        """True when ``level`` is within the [min, max] window."""
        return self.min <= float(level) <= self.max


@dataclass(frozen=True, slots=True)
class CapacityStatus:
    """Snapshot of how full a match is.

    A plain dataclass so views/serializers can render it without
    re-issuing count queries. The ``is_*`` flags are derived from
    ``player_count + companion_count`` and the match's lifecycle
    properties (cancelled, in_progress, finished).
    """

    match: Match
    player_count: int
    companion_count: int
    is_full: bool
    is_open: bool
    is_in_progress: bool
    is_finished: bool

    @property
    def total(self) -> int:
        """Players + companions — the actual 4-cap number."""
        return self.player_count + self.companion_count


# ---------------------------------------------------------------------------
# Match creation (host-first signup)
# ---------------------------------------------------------------------------
def create_match_from_slot(slot: MatchSlot, host: Any) -> Match:
    """Create a Match from an empty MatchSlot, with ``host`` as the first player.

    Validates:
    - Slot must not already be booked.
    - Host must have a non-null level (every new User defaults to 3.00,
      so this is only an issue for pre-migration or corrupted rows).

    Returns the created Match wrapped in a transaction. Raises
    ``ValueError`` for invalid input — the view layer maps that to
    HTTP 400 with the message.

    After commit, enqueues ``match_created`` notifications for
    subscribed members of the club via
    ``transaction.on_commit`` so the queue dispatch doesn't fire
    if the surrounding transaction rolls back.
    """
    if slot.booked_match_id is not None:
        raise ValueError(f"Slot {slot.pk} is already booked")

    if host.level is None:
        raise ValueError(f"Host {host.pk} has no level set")

    level_range = LevelRange.from_host(host.level)

    with transaction.atomic():
        match = Match.objects.create(
            host=host,
            level_min=Decimal(str(level_range.min)),
            level_max=Decimal(str(level_range.max)),
            is_cancelled=False,
        )
        MatchPlayer.objects.create(match=match, user=host)
        # Mark the slot as booked. Using a targeted update avoids a
        # full slot row write and keeps the FK clean.
        slot.booked_match = match
        slot.save(update_fields=["booked_match"])
        # Schedule the notification fan-out AFTER the surrounding
        # transaction commits, so a rollback doesn't leave queued
        # tasks pointing at a non-existent match.
        transaction.on_commit(
            lambda: _enqueue_match_created_safe(match.pk)
        )
        return match


def _enqueue_match_created_safe(match_id: int) -> None:
    """Wrapper that swallows exceptions so on_commit callbacks never break the request.

    Q2 ``.delay()`` itself should never fail (it just writes a row
    to the ORM broker), but a missing club FK or unexpected schema
    drift shouldn't propagate back into the response. Failures are
    logged at WARNING.
    """
    import logging

    from notifications.services import enqueue_match_created

    logger = logging.getLogger(__name__)
    try:
        enqueue_match_created(match_id=match_id)
    except Exception:  # pragma: no cover - defensive
        logger.warning(
            "enqueue_match_created failed for match %s", match_id, exc_info=True
        )


# ---------------------------------------------------------------------------
# Join / leave
# ---------------------------------------------------------------------------
def join_match(match: Match, user: Any, force: bool = False) -> MatchPlayer:
    """Add a player to a match.

    - ``force=True`` skips the level-range check (admin override path).
    - Idempotent: if the user is already a MatchPlayer on this match,
      the existing row is returned.
    - Capacity: 4 total (MatchPlayer + Companion).

    Raises ``ValueError`` when the match is cancelled, full, or the
    user is outside the level range and ``force`` is False.

    On a freshly-created ``MatchPlayer``, schedules a
    ``player_joined`` notification via ``transaction.on_commit``
    (admin override path goes through the same call so an admin
    add is also observable to other players).
    """
    if match.is_cancelled:
        raise ValueError("Match is cancelled")

    # Idempotent — re-joining returns the existing row.
    existing = MatchPlayer.objects.filter(match=match, user=user).first()
    if existing is not None:
        return existing

    if match.is_full:
        raise ValueError("Match is full")

    level_range = LevelRange(match.level_min, match.level_max)
    if not force and not level_range.contains(user.level):
        raise ValueError(
            f"User level {user.level} out of range "
            f"[{level_range.min}, {level_range.max}]"
        )

    match_player = MatchPlayer.objects.create(match=match, user=user)
    transaction.on_commit(
        lambda: _enqueue_player_joined_safe(match.pk, user.pk)
    )
    return match_player


def leave_match(match: Match, user: Any) -> None:
    """Remove a player from a match.

    - The host cannot leave their own match (raises ``ValueError``).
      Per spec the host is bound to the match they created; if they
      need to cancel, the admin ``cancel`` endpoint is the path.
    - Idempotent: if the user is not a player, this is a no-op.

    After a player leaves, the match's derived ``is_full`` property
    drops to ``False`` automatically (the count drops below 4) — no
    explicit transition is needed to "revert to active".

    Schedules a ``player_left`` notification when a row was actually
    removed (not on the idempotent no-op).
    """
    if match.host_id == user.pk:
        raise ValueError("Host cannot leave their own match")

    deleted_count, _ = MatchPlayer.objects.filter(match=match, user=user).delete()
    if deleted_count:
        transaction.on_commit(
            lambda: _enqueue_player_left_safe(match.pk, user.pk)
        )


def _enqueue_player_joined_safe(match_id: int, user_id: int) -> None:
    """Defensive wrapper around ``enqueue_player_joined``.

    See ``_enqueue_match_created_safe`` for rationale.
    """
    import logging

    from notifications.services import enqueue_player_joined

    logger = logging.getLogger(__name__)
    try:
        enqueue_player_joined(match_id=match_id, joining_user_id=user_id)
    except Exception:  # pragma: no cover - defensive
        logger.warning(
            "enqueue_player_joined failed for match %s, user %s",
            match_id,
            user_id,
            exc_info=True,
        )


def _enqueue_player_left_safe(match_id: int, user_id: int) -> None:
    """Defensive wrapper around ``enqueue_player_left``.

    See ``_enqueue_match_created_safe`` for rationale.
    """
    import logging

    from notifications.services import enqueue_player_left

    logger = logging.getLogger(__name__)
    try:
        enqueue_player_left(match_id=match_id, leaving_user_id=user_id)
    except Exception:  # pragma: no cover - defensive
        logger.warning(
            "enqueue_player_left failed for match %s, user %s",
            match_id,
            user_id,
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Capacity snapshot
# ---------------------------------------------------------------------------
def get_capacity_status(match: Match) -> CapacityStatus:
    """Return a snapshot of match capacity and derived states.

    Issues the count queries here so views/serializers don't have to
    think about reverse-relation prefetching. The dataclass is the
    single shape the API exposes for capacity — see the
    ``MatchSerializer.get_capacity`` implementation.
    """
    player_count = MatchPlayer.objects.filter(match=match).count()
    # Local import to avoid an import cycle at module load time
    # (companions app imports nothing from matches, but we want the
    # dependency to be a soft one in case the module is reused).
    from companions.models import Companion

    companion_count = Companion.objects.filter(match=match).count()
    total = player_count + companion_count
    now = timezone.now()
    slot = match.slot
    is_in_progress = bool(
        slot is not None
        and not match.is_cancelled
        and slot.start_time <= now < slot.end_time
    )
    is_finished = bool(
        slot is not None
        and not match.is_cancelled
        and now >= slot.end_time
    )
    return CapacityStatus(
        match=match,
        player_count=player_count,
        companion_count=companion_count,
        is_full=(total >= 4),
        is_open=(total < 4 and not match.is_cancelled),
        is_in_progress=is_in_progress,
        is_finished=is_finished,
    )
