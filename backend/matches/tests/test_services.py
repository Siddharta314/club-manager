"""Tests for the matches app — service layer.

Covers the business rules in ``matches.services``:

- ``LevelRange.from_host`` / ``LevelRange.contains`` — the ±0.25
  level matching math, including boundary cases.
- ``create_match_from_slot`` — host-first signup, level range
  derivation, slot.booked_match linkage, validation rejections.
- ``join_match`` — idempotency, level-range enforcement, admin
  override via ``force=True``, full / cancelled rejections.
- ``leave_match`` — host guard, idempotency.
- ``get_capacity_status`` — counts and derived flags.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from clubs.models import Club, Court
from companions.models import Companion
from match_slots.models import MatchSlot
from matches.models import Match, MatchPlayer
from matches.services import (
    CapacityStatus,
    LevelRange,
    create_match_from_slot,
    get_capacity_status,
    join_match,
    leave_match,
)
from players.models import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_court_and_slot(start_offset_minutes: int = 60) -> tuple[Court, MatchSlot]:
    """Create a Court and a future MatchSlot for use in match tests.

    Returned as a tuple so individual tests can pull either piece.
    """
    creator = User.objects.create(username="c_creator", email="c_creator@example.com")
    club = Club.objects.create(name="CT", address="CT 1", created_by=creator)
    court = Court.objects.create(club=club, name="CT Court")
    start = timezone.now() + timedelta(minutes=start_offset_minutes)
    slot = MatchSlot.objects.create(
        court=court,
        start_time=start,
        end_time=start + timedelta(minutes=90),
    )
    return court, slot


# ---------------------------------------------------------------------------
# LevelRange
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestLevelRange:
    """Pure dataclass — no DB needed for these tests."""

    def test_from_host_uses_centre_with_quarter_step(self) -> None:
        # 3.50 → [3.25, 3.75]
        r = LevelRange.from_host(3.50)
        assert r.min == 3.25
        assert r.max == 3.75

    def test_from_host_handles_decimal_input(self) -> None:
        # Decimal input (matches what the model returns).
        from decimal import Decimal

        r = LevelRange.from_host(Decimal("4.00"))
        assert r.min == 3.75
        assert r.max == 4.25

    def test_contains_at_exact_min(self) -> None:
        r = LevelRange(min=3.25, max=3.75)
        assert r.contains(3.25) is True

    def test_contains_at_exact_max(self) -> None:
        r = LevelRange(min=3.25, max=3.75)
        assert r.contains(3.75) is True

    def test_contains_at_centre(self) -> None:
        r = LevelRange(min=3.25, max=3.75)
        assert r.contains(3.50) is True

    def test_contains_just_outside(self) -> None:
        r = LevelRange(min=3.25, max=3.75)
        assert r.contains(3.24) is False
        assert r.contains(3.76) is False

    def test_contains_far_outside(self) -> None:
        r = LevelRange(min=3.25, max=3.75)
        assert r.contains(5.00) is False
        assert r.contains(1.00) is False


# ---------------------------------------------------------------------------
# create_match_from_slot
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCreateMatchFromSlot:
    def test_creates_match_with_host_and_first_player(self) -> None:
        _, slot = _make_court_and_slot()
        host = User.objects.create(username="h", email="h@example.com")
        match = create_match_from_slot(slot=slot, host=host)
        assert match.host == host
        assert match.players.filter(user=host).exists()
        # The host is the first player and is_host resolves correctly.
        mp = match.players.get(user=host)
        assert mp.is_host is True

    def test_sets_level_range_from_host_level(self) -> None:
        _, slot = _make_court_and_slot()
        host = User.objects.create(
            username="hl", email="hl@example.com", level=3.50
        )
        match = create_match_from_slot(slot=slot, host=host)
        # 3.50 ± 0.25 → [3.25, 3.75]; coerce to float to avoid
        # Decimal/Decimal comparisons being exact.
        assert float(match.level_min) == 3.25
        assert float(match.level_max) == 3.75

    def test_marks_slot_as_booked(self) -> None:
        _, slot = _make_court_and_slot()
        host = User.objects.create(username="hs", email="hs@example.com")
        match = create_match_from_slot(slot=slot, host=host)
        slot.refresh_from_db()
        assert slot.booked_match_id == match.pk

    def test_rejects_already_booked_slot(self) -> None:
        _, slot = _make_court_and_slot()
        # Pre-book the slot.
        existing_host = User.objects.create(
            username="ex", email="ex@example.com"
        )
        create_match_from_slot(slot=slot, host=existing_host)
        # Second attempt should fail.
        other = User.objects.create(username="ot", email="ot@example.com")
        with pytest.raises(ValueError, match="already booked"):
            create_match_from_slot(slot=slot, host=other)

    def test_marks_slot_as_booked(self) -> None:
        _, slot = _make_court_and_slot()
        host = User.objects.create(username="hs", email="hs@example.com")
        match = create_match_from_slot(slot=slot, host=host)
        slot.refresh_from_db()
        assert slot.booked_match_id == match.pk

    def test_rejects_already_booked_slot(self) -> None:
        _, slot = _make_court_and_slot()
        # Pre-book the slot.
        existing_host = User.objects.create(
            username="ex", email="ex@example.com"
        )
        create_match_from_slot(slot=slot, host=existing_host)
        # Second attempt should fail.
        other = User.objects.create(username="ot", email="ot@example.com")
        with pytest.raises(ValueError, match="already booked"):
            create_match_from_slot(slot=slot, host=other)

    def test_host_with_null_level_is_rejected(self) -> None:
        # The service has a defensive ``host.level is None`` check
        # that is unreachable through the model layer (the ``level``
        # column is NOT NULL), but worth pinning in a unit-style
        # test. We construct a User-like stub with ``level=None`` so
        # we exercise the branch without hitting the DB constraint.
        from types import SimpleNamespace

        _, slot = _make_court_and_slot()
        host_stub = SimpleNamespace(pk=999, level=None)
        with pytest.raises(ValueError, match="no level"):
            create_match_from_slot(slot=slot, host=host_stub)


# ---------------------------------------------------------------------------
# join_match
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestJoinMatch:
    def _match_with_host(self, host_level: float = 3.50):
        _, slot = _make_court_and_slot()
        host = User.objects.create(
            username="jhost", email="jhost@example.com", level=host_level
        )
        match = create_match_from_slot(slot=slot, host=host)
        return match, host, slot

    def test_join_in_range(self) -> None:
        match, host, _ = self._match_with_host(host_level=3.50)
        # Player 3.60 is within [3.25, 3.75].
        player = User.objects.create(
            username="p_in", email="p_in@example.com", level=3.60
        )
        join_match(match=match, user=player)
        assert match.players.filter(user=player).exists()

    def test_join_out_of_range_rejected(self) -> None:
        match, _, _ = self._match_with_host(host_level=3.50)
        player = User.objects.create(
            username="p_out", email="p_out@example.com", level=4.50
        )
        with pytest.raises(ValueError, match="out of range"):
            join_match(match=match, user=player)
        assert not match.players.filter(user=player).exists()

    def test_join_admin_override_accepts_out_of_range(self) -> None:
        match, _, _ = self._match_with_host(host_level=3.50)
        player = User.objects.create(
            username="p_force", email="p_force@example.com", level=4.50
        )
        join_match(match=match, user=player, force=True)
        assert match.players.filter(user=player).exists()

    def test_join_is_idempotent(self) -> None:
        match, host, _ = self._match_with_host(host_level=3.50)
        # Joining the same user twice returns the same row, doesn't
        # create a duplicate.
        join_match(match=match, user=host)
        join_match(match=match, user=host)
        assert match.players.filter(user=host).count() == 1

    def test_join_full_match_rejected(self) -> None:
        match, host, _ = self._match_with_host(host_level=3.50)
        # Fill the match: 1 host already present, 3 more players.
        for i in range(3):
            other = User.objects.create(
                username=f"fill_{i}", email=f"f_{i}@example.com", level=3.50
            )
            join_match(match=match, user=other)
        assert match.is_full is True
        # Fifth player is rejected.
        late = User.objects.create(
            username="late", email="late@example.com", level=3.50
        )
        with pytest.raises(ValueError, match="full"):
            join_match(match=match, user=late)

    def test_join_cancelled_match_rejected(self) -> None:
        match, _, _ = self._match_with_host(host_level=3.50)
        match.is_cancelled = True
        match.save()
        player = User.objects.create(
            username="p_c", email="p_c@example.com", level=3.50
        )
        with pytest.raises(ValueError, match="cancelled"):
            join_match(match=match, user=player)


# ---------------------------------------------------------------------------
# leave_match
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestLeaveMatch:
    def test_leave_removes_player(self) -> None:
        _, slot = _make_court_and_slot()
        host = User.objects.create(
            username="lh", email="lh@example.com", level=3.50
        )
        match = create_match_from_slot(slot=slot, host=host)
        player = User.objects.create(
            username="lp", email="lp@example.com", level=3.40
        )
        join_match(match=match, user=player)
        leave_match(match=match, user=player)
        assert not match.players.filter(user=player).exists()

    def test_leave_host_rejected(self) -> None:
        _, slot = _make_court_and_slot()
        host = User.objects.create(username="lr", email="lr@example.com")
        match = create_match_from_slot(slot=slot, host=host)
        with pytest.raises(ValueError, match="Host cannot leave"):
            leave_match(match=match, user=host)

    def test_leave_is_idempotent_for_non_player(self) -> None:
        _, slot = _make_court_and_slot()
        host = User.objects.create(username="li", email="li@example.com")
        match = create_match_from_slot(slot=slot, host=host)
        bystander = User.objects.create(
            username="by", email="by@example.com"
        )
        # Should not raise — the user simply isn't in the match.
        leave_match(match=match, user=bystander)
        assert not match.players.filter(user=bystander).exists()

    def test_leave_reverts_full_to_open(self) -> None:
        # Spec: "Leave from full MUST revert to active."
        _, slot = _make_court_and_slot()
        host = User.objects.create(
            username="lr2", email="lr2@example.com", level=3.50
        )
        match = create_match_from_slot(slot=slot, host=host)
        # Add 3 more players to fill (3.50 is in range).
        for i in range(3):
            p = User.objects.create(
                username=f"f_{i}", email=f"f_{i}@example.com", level=3.50
            )
            join_match(match=match, user=p)
        assert match.is_full is True
        # One leaves — match is no longer full.
        late_player = User.objects.create(
            username="late_l", email="late_l@example.com", level=3.50
        )
        # Need one of the existing players to leave (not the host).
        second_player = match.players.exclude(user=host).first()
        leave_match(match=match, user=second_player.user)
        match.refresh_from_db()
        assert match.is_full is False


# ---------------------------------------------------------------------------
# get_capacity_status
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetCapacityStatus:
    def test_empty_match(self) -> None:
        _, slot = _make_court_and_slot()
        host = User.objects.create(username="gc", email="gc@example.com")
        match = create_match_from_slot(slot=slot, host=host)
        status = get_capacity_status(match)
        # Host is automatically a MatchPlayer on creation.
        assert isinstance(status, CapacityStatus)
        assert status.player_count == 1
        assert status.companion_count == 0
        assert status.is_full is False
        assert status.is_open is True

    def test_match_full_at_four(self) -> None:
        _, slot = _make_court_and_slot()
        host = User.objects.create(
            username="gf", email="gf@example.com", level=3.50
        )
        match = create_match_from_slot(slot=slot, host=host)
        # 3 more players to reach 4.
        for i in range(3):
            p = User.objects.create(
                username=f"gp_{i}", email=f"gp_{i}@example.com", level=3.50
            )
            join_match(match=match, user=p)
        status = get_capacity_status(match)
        assert status.player_count == 4
        assert status.companion_count == 0
        assert status.is_full is True
        assert status.is_open is False

    def test_companions_count_toward_total(self) -> None:
        _, slot = _make_court_and_slot()
        host = User.objects.create(
            username="gc1", email="gc1@example.com", level=3.50
        )
        match = create_match_from_slot(slot=slot, host=host)
        # 1 host + 1 player = 2, then 2 companions = 4.
        player = User.objects.create(
            username="gc2", email="gc2@example.com", level=3.50
        )
        join_match(match=match, user=player)
        for i in range(2):
            Companion.objects.create(
                match=match, sponsored_by=host, name=f"G{i}", level=3.50
            )
        status = get_capacity_status(match)
        assert status.player_count == 2
        assert status.companion_count == 2
        assert status.is_full is True
        assert status.total == 4

    def test_cancelled_match_is_not_open(self) -> None:
        _, slot = _make_court_and_slot()
        host = User.objects.create(
            username="gc3", email="gc3@example.com", level=3.50
        )
        match = create_match_from_slot(slot=slot, host=host)
        match.is_cancelled = True
        match.save()
        status = get_capacity_status(match)
        assert status.is_open is False
