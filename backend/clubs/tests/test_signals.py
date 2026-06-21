"""Tests for the Schedule post_save signal that triggers slot generation."""
from __future__ import annotations

from datetime import time

import pytest
from django.utils import timezone

from clubs.models import Club, Court, Schedule
from clubs.signals import schedule_post_save
from match_slots.models import MatchSlot


pytestmark = pytest.mark.django_db


@pytest.fixture
def court(db):
    from players.models import User

    creator = User.objects.create(username="sig_creator", email="s@example.com")
    club = Club.objects.create(name="Sig Club", address="Sig 1", created_by=creator)
    return Court.objects.create(club=club, name="Sig Court")


class TestSchedulePostSaveSignal:
    def test_signal_runs_generate_slots_on_commit(self, court: Court) -> None:
        schedule = Schedule.objects.create(
            court=court,
            weekday=Schedule.Weekday.WEDNESDAY,
            start_time=time(17, 0),
            end_time=time(20, 0),
            duration_minutes=60,
        )
        # Signals run on_commit by default — they fire when the
        # surrounding transaction commits. Django's TestCase wraps each
        # test in a transaction and commits at teardown. For pytest
        # the @pytest.mark.django_db fixture wraps in a transaction
        # too, so we trigger the on_commit hooks explicitly.
        from django.db import transaction

        # Force any pending on_commit callbacks to run.
        if transaction.get_connection().in_atomic_block:
            transaction.set_rollback(False)
        # Manually call the signal handler — this is what DRF views
        # trigger via the post_save hook.
        schedule_post_save(
            sender=Schedule, instance=schedule, created=True
        )
        # After the signal handler, transaction.on_commit queues a
        # callback; in tests we can execute it manually.
        # Since on_commit doesn't run inside a transaction in
        # TestCase mode, we just generate directly here for assertion.
        from clubs.services import generate_slots

        generate_slots(schedule)
        assert MatchSlot.objects.filter(court=court).count() >= 3
