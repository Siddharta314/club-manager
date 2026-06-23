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
- ``cancel_match`` — sets ``is_cancelled``, fans out notifications,
  second call is a silent no-op (idempotency).
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from clubs.models import Club, Court
from companions.models import Companion
from match_slots.models import MatchSlot
from matches.models import Match, MatchPlayer
from matches.services import (
    CapacityStatus,
    LevelRange,
    cancel_match,
    create_match_from_slot,
    get_capacity_status,
    join_match,
    leave_match,
)
from players.models import User


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def patched_send_delay(monkeypatch):
    """Patch ``notifications.tasks.send_notification`` so tests inspect queued calls.

    Mirrors the same fixture in ``notifications/tests/test_services.py``
    so we can assert on ``send_notification.delay.call_args_list``
    without a live Q2 broker.
    """
    mock = MagicMock()
    import notifications.tasks as tasks_module

    monkeypatch.setattr(tasks_module, "send_notification", mock)
    return mock


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


# ---------------------------------------------------------------------------
# cancel_match
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCancelMatch:
    """Tests for the ``cancel_match`` service (REQ-WIRE-006, REQ-WIRE-008).

    The cancel path is the only lifecycle event that fans out
    notifications to every MatchPlayer (host included). The
    idempotency guard makes a second call a silent no-op so a
    double-click from the admin UI doesn't enqueue a second batch.
    """

    def _make_match_with_players(self):
        """Create a court + slot + host + 2 joined players + match.

        Returns ``(match, host, player1, player2)`` so each test can
        assert against the recipient set it expects.
        """
        _, slot = _make_court_and_slot()
        host = User.objects.create(
            username="c_host", email="c_host@example.com", level=3.50
        )
        match = create_match_from_slot(slot=slot, host=host)
        player1 = User.objects.create(
            username="c_p1", email="c_p1@example.com", level=3.50
        )
        player2 = User.objects.create(
            username="c_p2", email="c_p2@example.com", level=3.50
        )
        # Use ``force=True`` to skip the level-range check; this test
        # only cares about the cancel-side wiring.
        join_match(match=match, user=player1, force=True)
        join_match(match=match, user=player2, force=True)
        return match, host, player1, player2

    def test_sets_is_cancelled_to_true(
        self, patched_send_delay, django_capture_on_commit_callbacks
    ) -> None:
        """cancel_match sets match.is_cancelled to True (REQ-WIRE-006)."""
        match, _, _, _ = self._make_match_with_players()
        with django_capture_on_commit_callbacks(execute=True):
            cancel_match(match)
        match.refresh_from_db()
        assert match.is_cancelled is True

    def test_enqueues_notification_on_commit(
        self, patched_send_delay, django_capture_on_commit_callbacks
    ) -> None:
        """cancel_match fires send_notification.delay once per MatchPlayer on commit.

        Recipient set is host + 2 joined players (3 total). The
        on_commit callback must run inside
        ``django_capture_on_commit_callbacks(execute=True)`` so the
        helper actually fires under the test's rolled-back transaction.
        """
        match, host, player1, player2 = self._make_match_with_players()
        # Reset the mock so the join-time ``player_joined`` calls don't
        # pollute the cancel-side assertion.
        patched_send_delay.reset_mock()
        with django_capture_on_commit_callbacks(execute=True):
            cancel_match(match)
        # host + 2 joined = 3 notifications
        assert patched_send_delay.delay.call_count == 3
        called_user_ids = {
            call.kwargs["user_id"]
            for call in patched_send_delay.delay.call_args_list
        }
        assert called_user_ids == {host.pk, player1.pk, player2.pk}

    def test_idempotent_second_call_is_silent(
        self, patched_send_delay, django_capture_on_commit_callbacks
    ) -> None:
        """A second cancel_match call is a silent no-op (REQ-WIRE-006 idempotency).

        The first call enqueues one batch; the second call MUST NOT
        register a new ``on_commit`` and MUST NOT call ``match.save``
        again. Resetting the mock between calls lets us see only the
        second call's effect (which must be zero).
        """
        match, _, _, _ = self._make_match_with_players()
        # First call: fires on_commit, 3 notifications queued
        with django_capture_on_commit_callbacks(execute=True):
            cancel_match(match)
        first_call_count = patched_send_delay.delay.call_count
        assert first_call_count == 3

        # Reset the mock so the second call's effect is visible
        patched_send_delay.reset_mock()

        # Second call: must be a no-op (no new on_commit registration,
        # no save, no further notifications scheduled)
        with django_capture_on_commit_callbacks(execute=True):
            cancel_match(match)

        # No new notifications fired
        assert patched_send_delay.delay.call_count == 0
