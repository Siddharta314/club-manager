"""Tests for the clubs app — Club, Court, Schedule.

Covers the address-required invariant, the (name, address) uniqueness
constraint, and the Schedule -> Court relationship.
"""
from datetime import time

import pytest
from django.db import IntegrityError, transaction

from clubs.models import Club, Court, Schedule


@pytest.mark.django_db
class TestClub:
    def _make_creator(self):
        from players.models import User

        return User.objects.create(username="creator", email="creator@example.com")

    def test_creation_stores_required_fields(self):
        creator = self._make_creator()
        club = Club.objects.create(
            name="Club A",
            address="Calle Mayor 1, Madrid",
            created_by=creator,
        )
        assert club.name == "Club A"
        assert club.address == "Calle Mayor 1, Madrid"
        assert club.created_by == creator
        assert club.created_at is not None
        assert club.updated_at is not None

    def test_address_is_required(self):
        """Creating a club without an address must fail."""
        creator = self._make_creator()
        with pytest.raises((IntegrityError, ValueError)), transaction.atomic():
            Club.objects.create(name="No Address", created_by=creator)

    def test_duplicate_name_and_address_rejected(self):
        creator = self._make_creator()
        Club.objects.create(
            name="Dup", address="Same St 1", created_by=creator
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            Club.objects.create(
                name="Dup", address="Same St 1", created_by=creator
            )

    def test_same_name_different_address_allowed(self):
        creator = self._make_creator()
        Club.objects.create(name="X", address="Addr 1", created_by=creator)
        Club.objects.create(name="X", address="Addr 2", created_by=creator)
        assert Club.objects.filter(name="X").count() == 2


@pytest.mark.django_db
class TestCourt:
    def _club(self):
        from players.models import User

        creator = User.objects.create(username="c1", email="c1@example.com")
        return Club.objects.create(name="C", address="A", created_by=creator)

    def test_court_belongs_to_club(self):
        club = self._club()
        court = Court.objects.create(club=club, name="Court 1")
        assert court.club == club
        assert court.is_active is True

    def test_court_inherits_club_on_delete(self):
        club = self._club()
        court = Court.objects.create(club=club, name="X")
        club_id = club.id
        club.delete()
        assert not Court.objects.filter(pk=court.pk).exists()

    def test_unique_court_name_within_club(self):
        club = self._club()
        Court.objects.create(club=club, name="Solo")
        with pytest.raises(IntegrityError), transaction.atomic():
            Court.objects.create(club=club, name="Solo")


@pytest.mark.django_db
class TestSchedule:
    def _club_and_court(self):
        from players.models import User

        creator = User.objects.create(username="sc", email="sc@example.com")
        club = Club.objects.create(name="SC", address="SA", created_by=creator)
        court = Court.objects.create(club=club, name="Court A")
        return club, court

    def test_schedule_creation(self):
        club, court = self._club_and_court()
        sched = Schedule.objects.create(
            court=court,
            weekday=Schedule.Weekday.MONDAY,
            start_time=time(17, 0),
            end_time=time(21, 0),
            duration_minutes=60,
        )
        assert sched.court == court
        assert sched.weekday == 0
        assert sched.duration_minutes == 60

    def test_schedule_duration_min_must_be_15_or_more(self):
        from django.core.exceptions import ValidationError

        club, court = self._club_and_court()
        sched = Schedule(
            court=court,
            weekday=Schedule.Weekday.FRIDAY,
            start_time=time(17, 0),
            end_time=time(18, 0),
            duration_minutes=10,
        )
        with pytest.raises(ValidationError):
            sched.full_clean()

    def test_schedule_cascade_deletes_with_court(self):
        club, court = self._club_and_court()
        Schedule.objects.create(
            court=court,
            weekday=Schedule.Weekday.TUESDAY,
            start_time=time(17, 0),
            end_time=time(20, 0),
            duration_minutes=60,
        )
        court_id = court.id
        court.delete()
        assert not Schedule.objects.filter(court_id=court_id).exists()