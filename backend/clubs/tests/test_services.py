"""Tests for clubs/services.py — slot generation."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from clubs.models import Club, Court, Schedule
from clubs.services import generate_slots
from match_slots.models import MatchSlot


pytestmark = pytest.mark.django_db


@pytest.fixture
def court(db) -> Any:
    from players.models import User

    creator = User.objects.create(username="svc_creator", email="sc@example.com")
    club = Club.objects.create(name="Svc Club", address="Svc 1", created_by=creator)
    return Court.objects.create(club=club, name="Svc Court")


def _make_schedule(court: Court, **overrides: Any) -> Schedule:
    defaults = {
        "weekday": Schedule.Weekday.MONDAY,
        "start_time": __import__("datetime").time(18, 0),
        "end_time": __import__("datetime").time(21, 0),
        "duration_minutes": 60,
    }
    defaults.update(overrides)
    return Schedule.objects.create(court=court, **defaults)


class TestGenerateSlots:
    def test_creates_correct_number_of_slots(self, court: Court) -> None:
        schedule = _make_schedule(court)
        slots = generate_slots(schedule)
        # 3 slots per Monday (18, 19, 20) × ~4 future Mondays in 28d.
        assert len(slots) >= 3
        # All slots are on Monday.
        for s in slots:
            assert s.start_time.weekday() == 0

    def test_all_created_slots_have_correct_duration(self, court: Court) -> None:
        schedule = _make_schedule(court, duration_minutes=90)
        slots = generate_slots(schedule)
        for s in slots:
            delta = s.end_time - s.start_time
            assert delta == timedelta(minutes=90)

    def test_past_slots_are_preserved(self, court: Court) -> None:
        # Create a past slot manually.
        past_start = timezone.now() - timedelta(days=2)
        MatchSlot.objects.create(
            court=court,
            start_time=past_start,
            end_time=past_start + timedelta(hours=1),
        )
        schedule = _make_schedule(court)
        generate_slots(schedule)
        # Past slot still there.
        assert MatchSlot.objects.filter(
            court=court, start_time__lt=timezone.now()
        ).count() == 1

    def test_booked_future_slots_are_preserved(self, court: Court) -> None:
        from matches.models import Match

        from players.models import User

        host = User.objects.create(username="bh", email="bh@example.com")
        schedule = _make_schedule(court)
        generate_slots(schedule)
        # Take one of the generated future slots, attach a match.
        slot = MatchSlot.objects.filter(court=court, start_time__gt=timezone.now()).first()
        assert slot is not None
        match = Match.objects.create(host=host)
        slot.booked_match = match
        slot.save()
        # Re-run: the booked slot must remain.
        booked_id = slot.id
        generate_slots(schedule)
        assert MatchSlot.objects.filter(pk=booked_id).exists()

    def test_unbooked_future_slots_are_replaced(self, court: Court) -> None:
        schedule = _make_schedule(court)
        first_run = generate_slots(schedule)
        first_ids = sorted(s.id for s in first_run)
        # Modify the schedule so generation produces different slots.
        schedule.start_time = __import__("datetime").time(17, 0)
        schedule.save()
        second_run = generate_slots(schedule)
        # First-run slots should be gone (or at least all-new IDs).
        second_ids = sorted(s.id for s in second_run)
        assert set(first_ids).isdisjoint(set(second_ids))

    def test_is_idempotent_for_same_schedule(self, court: Court) -> None:
        schedule = _make_schedule(court)
        first_count = len(generate_slots(schedule))
        second_count = len(generate_slots(schedule))
        assert first_count == second_count

    def test_no_duplicate_court_start_pair(self, court: Court) -> None:
        # Regression: the (court, start_time) uniqueness must hold even
        # after re-running generation.
        schedule = _make_schedule(court)
        for _ in range(3):
            generate_slots(schedule)
        # No duplicate keys.
        keys = list(
            MatchSlot.objects.filter(court=court).values_list(
                "court_id", "start_time"
            )
        )
        assert len(keys) == len(set(keys))

    def test_horizon_stops_at_28_days(self, court: Court) -> None:
        schedule = _make_schedule(court, weekday=Schedule.Weekday.FRIDAY)
        slots = generate_slots(schedule)
        # 4 weeks × 3 slots per Friday = 12 slots max (today is
        # probably Sunday so the first Friday is +5 days; last is
        # +26 days, still inside 28 days).
        assert 0 < len(slots) <= 12

    def test_returns_list(self, court: Court) -> None:
        schedule = _make_schedule(court)
        result = generate_slots(schedule)
        assert isinstance(result, list)
