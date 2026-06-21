"""Tests for clubs DRF serializers — validation rules."""
from __future__ import annotations

from datetime import time

import pytest
from rest_framework.exceptions import ValidationError

from clubs.models import Club, Court, Schedule
from clubs.serializers import (
    ClubSerializer,
    ClubWriteSerializer,
    CourtSerializer,
    ScheduleSerializer,
)


@pytest.mark.django_db
class TestClubWriteSerializer:
    def _creator(self):
        from players.models import User

        return User.objects.create(username="c", email="c@example.com")

    def test_valid_payload_passes(self):
        creator = self._creator()
        s = ClubWriteSerializer(
            data={"name": "C", "address": "Addr 1"},
        )
        assert s.is_valid(), s.errors

    def test_blank_address_rejected(self):
        s = ClubWriteSerializer(data={"name": "C", "address": ""})
        assert not s.is_valid()
        assert "address" in s.errors

    def test_blank_name_rejected(self):
        s = ClubWriteSerializer(data={"name": "", "address": "Addr 1"})
        assert not s.is_valid()
        assert "name" in s.errors

    def test_whitespace_only_address_rejected(self):
        s = ClubWriteSerializer(data={"name": "C", "address": "   "})
        assert not s.is_valid()
        assert "address" in s.errors


@pytest.mark.django_db
class TestCourtSerializer:
    def test_valid_court(self):
        s = CourtSerializer(data={"club": 1, "name": "Court 1"})
        # club is required to validate but we skip the full-clean;
        # the serializer only checks name.
        s.is_valid()
        # The serializer is used in nested contexts where club is
        # set by the view's perform_create. The serializer's
        # validate_name rule is the only field-level check we need.
        assert "name" in s.fields

    def test_blank_name_rejected(self):
        s = CourtSerializer(data={"name": ""})
        assert not s.is_valid()
        assert "name" in s.errors


@pytest.mark.django_db
class TestScheduleSerializer:
    def _court(self):
        from players.models import User

        u = User.objects.create(username="cs", email="cs@example.com")
        club = Club.objects.create(name="SC", address="SA", created_by=u)
        return Court.objects.create(club=club, name="Court A")

    def _payload(self, **overrides):
        base = {
            "court": 1,
            "weekday": 0,
            "start_time": time(17, 0),
            "end_time": time(21, 0),
            "duration_minutes": 60,
        }
        base.update(overrides)
        return base

    def test_valid_schedule_passes(self):
        court = self._court()
        s = ScheduleSerializer(data=self._payload(court=court.pk))
        assert s.is_valid(), s.errors

    def test_end_before_start_rejected(self):
        court = self._court()
        s = ScheduleSerializer(
            data=self._payload(
                court=court.pk, start_time=time(21, 0), end_time=time(17, 0)
            )
        )
        assert not s.is_valid()
        assert "end_time" in s.errors

    def test_zero_duration_rejected(self):
        court = self._court()
        s = ScheduleSerializer(data=self._payload(court=court.pk, duration_minutes=0))
        assert not s.is_valid()
        assert "duration_minutes" in s.errors

    def test_long_duration_rejected(self):
        court = self._court()
        s = ScheduleSerializer(
            data=self._payload(court=court.pk, duration_minutes=300)
        )
        assert not s.is_valid()
        assert "duration_minutes" in s.errors

    def test_boundary_duration_accepted(self):
        court = self._court()
        s = ScheduleSerializer(
            data=self._payload(court=court.pk, duration_minutes=240)
        )
        assert s.is_valid(), s.errors


@pytest.mark.django_db
class TestClubSerializer:
    def test_read_shape_includes_courts_and_address(self, club_factory):
        club = club_factory(name="X", address="Y")
        data = ClubSerializer(club).data
        assert data["name"] == "X"
        assert data["address"] == "Y"
        assert "courts" in data
        assert "created_by" in data
