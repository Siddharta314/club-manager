"""Tests for the match_slots app — MatchSlot model.

Covers the (court, start_time) uniqueness invariant, the end > start
constraint, and the basic lifecycle helpers.
"""
from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from clubs.models import Club, Court
from match_slots.models import MatchSlot
from players.models import User


@pytest.fixture
def court(db):
    creator = User.objects.create(username="slot_creator", email="sc@example.com")
    club = Club.objects.create(name="Slot Club", address="Slot 1", created_by=creator)
    return Court.objects.create(club=club, name="Court A")


@pytest.mark.django_db
class TestMatchSlotBasics:
    def test_create_match_slot(self, court):
        start = timezone.now() + timedelta(days=1)
        end = start + timedelta(minutes=60)
        slot = MatchSlot.objects.create(court=court, start_time=start, end_time=end)
        assert slot.is_active is True
        assert slot.is_booked is False

    def test_unique_court_start_time_pair(self, court):
        start = timezone.now() + timedelta(days=2)
        end = start + timedelta(minutes=60)
        MatchSlot.objects.create(court=court, start_time=start, end_time=end)
        with pytest.raises(IntegrityError), transaction.atomic():
            MatchSlot.objects.create(court=court, start_time=start, end_time=end)

    def test_same_start_different_courts_allowed(self, court):
        creator = User.objects.create(username="creator2", email="c2@example.com")
        club2 = Club.objects.create(name="Other", address="O 1", created_by=creator)
        court2 = Court.objects.create(club=club2, name="Court B")
        start = timezone.now() + timedelta(days=3)
        end = start + timedelta(minutes=60)
        MatchSlot.objects.create(court=court, start_time=start, end_time=end)
        MatchSlot.objects.create(court=court2, start_time=start, end_time=end)
        assert MatchSlot.objects.filter(start_time=start).count() == 2


@pytest.mark.django_db
class TestMatchSlotConstraints:
    def test_end_must_be_after_start(self, court):
        start = timezone.now() + timedelta(days=1)
        with pytest.raises(IntegrityError), transaction.atomic():
            MatchSlot.objects.create(court=court, start_time=start, end_time=start)

    def test_subsecond_length_slot_is_allowed(self, court):
        """Constraint enforces end > start at microsecond granularity."""
        start = timezone.now() + timedelta(days=1)
        end = start + timedelta(microseconds=1)
        slot = MatchSlot.objects.create(court=court, start_time=start, end_time=end)
        assert slot.end_time > slot.start_time


@pytest.mark.django_db
class TestMatchSlotProperties:
    def test_is_future_true_for_future_start(self, court):
        start = timezone.now() + timedelta(hours=1)
        end = start + timedelta(minutes=60)
        slot = MatchSlot.objects.create(court=court, start_time=start, end_time=end)
        assert slot.is_future is True

    def test_is_future_false_for_past_start(self, court):
        start = timezone.now() - timedelta(hours=1)
        end = start + timedelta(minutes=60)
        slot = MatchSlot.objects.create(court=court, start_time=start, end_time=end)
        assert slot.is_future is False

    def test_cascade_delete_with_court(self, court):
        start = timezone.now() + timedelta(days=1)
        MatchSlot.objects.create(
            court=court, start_time=start, end_time=start + timedelta(hours=1)
        )
        court_id = court.id
        court.delete()
        assert not MatchSlot.objects.filter(court_id=court_id).exists()