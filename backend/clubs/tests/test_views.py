"""Tests for clubs DRF viewsets — CRUD endpoints + permissions."""
from __future__ import annotations

from datetime import time

import pytest
from rest_framework.test import APIClient

from auth_clerk.authentication import ClerkSessionAuthentication
from auth_clerk.middleware import ClerkJWTMiddleware
from clubs.models import Club, Court, Schedule
from players.models import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@pytest.fixture
def auth_client(bypass_clerk_auth, make_clerk_state, db):
    """Return an APIClient with the Clerk auth mocked to a given user.

    The fixture returns a callable that builds a client for a specific
    clerk_id so each test can pick its role/permissions freely. The
    returned client has a default ``HTTP_AUTHORIZATION`` so the
    ClerkJWTMiddleware accepts the request.

    Usage::

        def test_x(auth_client):
            client, user = auth_client("user_alice", role=User.Role.CLUB_ADMIN)
            client.get(...)
    """

    def _make(clerk_id: str, **user_kwargs):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user, _ = User.objects.get_or_create(
            clerk_user_id=clerk_id,
            defaults={
                "username": user_kwargs.pop("username", clerk_id),
                "email": user_kwargs.pop("email", f"{clerk_id}@example.com"),
            },
        )
        for field, value in user_kwargs.items():
            setattr(user, field, value)
        if user_kwargs:
            user.save()
        # Build a state whose payload carries the user id, so the
        # middleware auto-provisions / refreshes the row.
        state = make_clerk_state(
            sub=clerk_id, email=user.email, name=user.username
        )
        bypass_clerk_auth(state)
        client = APIClient()
        client.defaults["HTTP_AUTHORIZATION"] = "Bearer test.jwt.token"
        return client, user

    return _make


# ---------------------------------------------------------------------------
# ClubViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestClubViewSet:
    URL = "/api/v1/clubs/"

    def test_list_returns_200_for_authenticated_user(self, auth_client) -> None:
        client, _ = auth_client("user_l1")
        response = client.get(self.URL)
        assert response.status_code == 200

    def test_list_returns_401_for_unauthenticated(self, db) -> None:
        client = APIClient()
        response = client.get(self.URL)
        assert response.status_code == 401

    def test_create_sets_creator_and_returns_full_shape(self, auth_client) -> None:
        client, user = auth_client("user_creator")
        response = client.post(
            self.URL, {"name": "New", "address": "Addr"}, format="json"
        )
        assert response.status_code == 201, response.data
        assert response.data["name"] == "New"
        assert response.data["created_by"] == user.pk

    def test_create_with_blank_address_returns_400(self, auth_client) -> None:
        client, _ = auth_client("user_blank")
        response = client.post(
            self.URL, {"name": "X", "address": ""}, format="json"
        )
        assert response.status_code == 400
        assert "address" in response.data

    def test_non_admin_cannot_update_other_club(self, auth_client, club_factory) -> None:
        # Pre-create a club owned by a different user.
        from players.models import User

        creator = User.objects.create(username="other", email="o@example.com")
        club = Club.objects.create(name="Other", address="O", created_by=creator)
        client, _ = auth_client("user_player")
        response = client.patch(
            f"{self.URL}{club.pk}/",
            {"name": "Hacked"},
            format="json",
        )
        # player is not the club admin → 403.
        assert response.status_code == 403

    def test_club_admin_can_update_own_club(self, auth_client) -> None:
        client, user = auth_client("user_admin", role=User.Role.CLUB_ADMIN)
        # Create the club as this user so created_by == user.
        club = Club.objects.create(name="A", address="A1", created_by=user)
        # Mirror perform_create's auto-promote so the IsClubAdmin M2M
        # check passes.
        club.admins.add(user)
        response = client.patch(
            f"{self.URL}{club.pk}/",
            {"name": "Renamed"},
            format="json",
        )
        assert response.status_code == 200, response.data
        assert response.data["name"] == "Renamed"

    def test_super_admin_can_update_any_club(
        self, auth_client, club_factory
    ) -> None:
        club = club_factory(name="X", address="Y")
        client, _ = auth_client("user_super", role=User.Role.SUPER_ADMIN)
        response = client.patch(
            f"{self.URL}{club.pk}/",
            {"name": "Updated"},
            format="json",
        )
        assert response.status_code == 200, response.data
        assert response.data["name"] == "Updated"


# ---------------------------------------------------------------------------
# CourtViewSet
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCourtViewSet:
    def _club(self, creator):
        return Club.objects.create(name="C", address="A", created_by=creator)

    def test_club_admin_can_create_court(self, auth_client) -> None:
        client, user = auth_client("user_court_admin", role=User.Role.CLUB_ADMIN)
        club = self._club(user)
        # Mirror perform_create's auto-promote so the IsClubAdmin M2M
        # check passes for the nested Court create.
        club.admins.add(user)
        response = client.post(
            f"/api/v1/clubs/{club.pk}/courts/",
            {"name": "Court A"},
            format="json",
        )
        assert response.status_code == 201, response.data

    def test_non_admin_cannot_create_court(self, auth_client, user_factory) -> None:
        client, _ = auth_client("user_court_player")
        from players.models import User

        creator = User.objects.create(username="c_owner", email="co@example.com")
        club = self._club(creator)
        response = client.post(
            f"/api/v1/clubs/{club.pk}/courts/",
            {"name": "Court B"},
            format="json",
        )
        assert response.status_code == 403

    def test_list_returns_club_courts(self, auth_client) -> None:
        client, user = auth_client("user_list_courts", role=User.Role.CLUB_ADMIN)
        club = self._club(user)
        Court.objects.create(club=club, name="X")
        Court.objects.create(club=club, name="Y")
        response = client.get(f"/api/v1/clubs/{club.pk}/courts/")
        assert response.status_code == 200
        names = {c["name"] for c in response.data["results"]}
        assert names == {"X", "Y"}


# ---------------------------------------------------------------------------
# ScheduleViewSet + slot generation
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestScheduleViewSetAndSlotGeneration:
    def test_schedule_save_generates_slots(
        self, auth_client, django_capture_on_commit_callbacks
    ) -> None:
        from match_slots.models import MatchSlot

        client, user = auth_client(
            "user_sched_admin", role=User.Role.CLUB_ADMIN
        )
        club = Club.objects.create(name="SC", address="SA", created_by=user)
        # Mirror perform_create's auto-promote so the IsClubAdmin M2M
        # check passes for the nested Schedule create.
        club.admins.add(user)
        court = Court.objects.create(club=club, name="C1")
        # The post_save signal uses transaction.on_commit, which only
        # fires when the surrounding transaction commits. Inside
        # pytest-django's default db fixture the test runs in a
        # transaction that's rolled back, so on_commit never fires.
        # django_capture_on_commit_callbacks forces them to fire
        # synchronously after the test's writes.
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(
                f"/api/v1/clubs/{club.pk}/courts/{court.pk}/schedule/",
                {
                    "weekday": 0,
                    "start_time": time(18, 0),
                    "end_time": time(21, 0),
                    "duration_minutes": 60,
                },
                format="json",
            )
        assert response.status_code == 201, response.data
        # The signal's on_commit hook ran and generated slots.
        assert MatchSlot.objects.filter(court=court).count() >= 3

    def test_slot_listing_filters_past(self, auth_client) -> None:
        from datetime import timedelta
        from django.utils import timezone
        from match_slots.models import MatchSlot

        client, user = auth_client(
            "user_slot_list", role=User.Role.CLUB_ADMIN
        )
        club = Club.objects.create(name="SL", address="SL1", created_by=user)
        court = Court.objects.create(club=club, name="C1")
        # Past slot
        MatchSlot.objects.create(
            court=court,
            start_time=timezone.now() - timedelta(hours=2),
            end_time=timezone.now() - timedelta(hours=1),
        )
        # Future slot
        future = timezone.now() + timedelta(hours=2)
        MatchSlot.objects.create(
            court=court,
            start_time=future,
            end_time=future + timedelta(hours=1),
        )
        response = client.get(f"/api/v1/clubs/{club.pk}/slots/")
        assert response.status_code == 200
        # Only the future slot is returned.
        assert len(response.data) == 1
        assert response.data[0]["court_id"] == court.pk

    def test_slot_listing_filters_by_date(self, auth_client) -> None:
        from datetime import timedelta
        from django.utils import timezone
        from match_slots.models import MatchSlot

        client, user = auth_client(
            "user_slot_date", role=User.Role.CLUB_ADMIN
        )
        club = Club.objects.create(name="SD", address="SD1", created_by=user)
        court = Court.objects.create(club=club, name="C1")
        # Tomorrow
        tomorrow = timezone.now() + timedelta(days=1)
        MatchSlot.objects.create(
            court=court,
            start_time=tomorrow,
            end_time=tomorrow + timedelta(hours=1),
        )
        # Day-after-tomorrow
        dat = tomorrow + timedelta(days=1)
        MatchSlot.objects.create(
            court=court,
            start_time=dat,
            end_time=dat + timedelta(hours=1),
        )
        target = tomorrow.date().isoformat()
        response = client.get(f"/api/v1/clubs/{club.pk}/slots/?date={target}")
        assert response.status_code == 200
        assert len(response.data) == 1

    def test_slot_listing_invalid_date_returns_400(self, auth_client) -> None:
        client, user = auth_client(
            "user_slot_invalid", role=User.Role.CLUB_ADMIN
        )
        club = Club.objects.create(name="SI", address="SI1", created_by=user)
        response = client.get(f"/api/v1/clubs/{club.pk}/slots/?date=not-a-date")
        assert response.status_code == 400
