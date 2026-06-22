"""Tests for the companions app — DRF views.

Covers the HTTP layer for companion registration and removal:

- ``POST /api/v1/matches/{id}/companions/`` — register a companion
  on a match (sponsor or admin).
- ``DELETE /api/v1/companions/{id}/`` — remove a companion
  (sponsor or admin).
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from clubs.models import Club, Court
from match_slots.models import MatchSlot
from matches.services import create_match_from_slot, join_match
from players.models import User


# ---------------------------------------------------------------------------
# Helpers + fixtures
# ---------------------------------------------------------------------------
def _make_club_court_slot() -> tuple[Club, Court, MatchSlot]:
    """Create a Club + Court + future MatchSlot for companion view tests."""
    creator = User.objects.create(
        username="cv_creator", email="cv_creator@example.com"
    )
    club = Club.objects.create(name="CV", address="CV 1", created_by=creator)
    club.admins.add(creator)
    court = Court.objects.create(club=club, name="CV Court")
    start = timezone.now() + timedelta(hours=1)
    slot = MatchSlot.objects.create(
        court=court,
        start_time=start,
        end_time=start + timedelta(minutes=90),
    )
    return club, court, slot


@pytest.fixture
def auth_client(bypass_clerk_auth, make_clerk_state, db):
    """APIClient bound to a Clerk-authenticated user."""

    def _make(clerk_id: str, **user_kwargs):
        from django.contrib.auth import get_user_model

        UserModel = get_user_model()
        user, _ = UserModel.objects.get_or_create(
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
        state = make_clerk_state(
            sub=clerk_id, email=user.email, name=user.username
        )
        bypass_clerk_auth(state)
        client = APIClient()
        client.defaults["HTTP_AUTHORIZATION"] = "Bearer test.jwt.token"
        return client, user

    return _make


# ---------------------------------------------------------------------------
# RegisterCompanionView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRegisterCompanionView:
    URL_TMPL = "/api/v1/matches/{id}/companions/"

    def test_register_by_player_returns_201(self, auth_client) -> None:
        _, _, slot = _make_club_court_slot()
        client, host = auth_client("c_host", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        # Second player — can register a companion.
        client2, player = auth_client("c_player", level=3.50)
        join_match(match=match, user=player)
        response = client2.post(
            self.URL_TMPL.format(id=match.pk),
            {"name": "Alex", "level": 3.40},
            format="json",
        )
        assert response.status_code == 201, response.data
        assert response.data["name"] == "Alex"
        assert response.data["sponsored_by_id"] == player.pk

    def test_register_by_admin_returns_201(self, auth_client) -> None:
        # Admin who is not a player on the match.
        _, _, slot = _make_club_court_slot()
        client, host = auth_client("c_ah", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        # Create an admin user that's also a club admin of the match's club.
        client_admin, admin = auth_client("c_admin", role=User.Role.CLUB_ADMIN)
        from clubs.models import Club

        # The match's club is the one created in _make_club_court_slot;
        # we need to add the admin to its admins M2M.
        match_club = match.slot.court.club
        match_club.admins.add(admin)
        response = client_admin.post(
            self.URL_TMPL.format(id=match.pk),
            {"name": "Coach", "level": 3.80},
            format="json",
        )
        assert response.status_code == 201, response.data

    def test_register_by_outsider_returns_403(self, auth_client) -> None:
        _, _, slot = _make_club_court_slot()
        client, host = auth_client("c_h1", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        # User that's neither a player nor a club admin.
        client_out, _ = auth_client("c_outsider", level=3.50)
        response = client_out.post(
            self.URL_TMPL.format(id=match.pk),
            {"name": "Sneaky", "level": 3.50},
            format="json",
        )
        assert response.status_code == 403

    def test_register_when_full_returns_400(self, auth_client) -> None:
        _, _, slot = _make_club_court_slot()
        client, host = auth_client("c_h2", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        # Fill the match: 1 host + 3 more players = 4.
        for i in range(3):
            p = User.objects.create(
                username=f"f_{i}", email=f"f_{i}@example.com", level=3.50
            )
            join_match(match=match, user=p)
        assert match.is_full is True
        response = client.post(
            self.URL_TMPL.format(id=match.pk),
            {"name": "Late", "level": 3.40},
            format="json",
        )
        assert response.status_code == 400
        assert "full" in str(response.data).lower()

    def test_register_empty_name_returns_400(self, auth_client) -> None:
        _, _, slot = _make_club_court_slot()
        client, host = auth_client("c_h3", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        response = client.post(
            self.URL_TMPL.format(id=match.pk),
            {"name": "", "level": 3.40},
            format="json",
        )
        assert response.status_code == 400

    def test_register_invalid_level_returns_400(self, auth_client) -> None:
        _, _, slot = _make_club_court_slot()
        client, host = auth_client("c_h4", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        response = client.post(
            self.URL_TMPL.format(id=match.pk),
            {"name": "X", "level": 9.00},
            format="json",
        )
        assert response.status_code == 400

    def test_register_unknown_match_returns_404(self, auth_client) -> None:
        client, _ = auth_client("c_unm", level=3.50)
        response = client.post(
            self.URL_TMPL.format(id=999_999),
            {"name": "X", "level": 3.50},
            format="json",
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# CompanionDetailView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCompanionDetailView:
    URL_TMPL = "/api/v1/companions/{id}/"

    def test_delete_by_sponsor_returns_204(self, auth_client) -> None:
        _, _, slot = _make_club_court_slot()
        client, host = auth_client("c_dh", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        # Register a companion via the API.
        response = client.post(
            f"/api/v1/matches/{match.pk}/companions/",
            {"name": "Friend", "level": 3.40},
            format="json",
        )
        assert response.status_code == 201
        companion_id = response.data["id"]
        # Sponsor deletes.
        response = client.delete(self.URL_TMPL.format(id=companion_id))
        assert response.status_code == 204

    def test_delete_by_admin_returns_204(self, auth_client) -> None:
        # Sponsor registers via the API; admin deletes.
        _, _, slot = _make_club_court_slot()
        client, host = auth_client("c_dh2", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        response = client.post(
            f"/api/v1/matches/{match.pk}/companions/",
            {"name": "Coach", "level": 3.40},
            format="json",
        )
        assert response.status_code == 201
        companion_id = response.data["id"]
        # Switch to an admin user who is admin of the match's club.
        client_admin, admin = auth_client("c_da", role=User.Role.CLUB_ADMIN)
        match.slot.court.club.admins.add(admin)
        response = client_admin.delete(self.URL_TMPL.format(id=companion_id))
        assert response.status_code == 204

    def test_delete_by_other_user_returns_403(self, auth_client) -> None:
        _, _, slot = _make_club_court_slot()
        client, host = auth_client("c_dh3", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        # Sponsor registers.
        response = client.post(
            f"/api/v1/matches/{match.pk}/companions/",
            {"name": "Mine", "level": 3.40},
            format="json",
        )
        assert response.status_code == 201
        companion_id = response.data["id"]
        # A different user (also a player on the match, but not the
        # sponsor) tries to delete.
        client_other, other = auth_client("c_other", level=3.50)
        join_match(match=match, user=other)
        response = client_other.delete(self.URL_TMPL.format(id=companion_id))
        assert response.status_code == 403

    def test_delete_unknown_companion_returns_404(self, auth_client) -> None:
        client, _ = auth_client("c_du", level=3.50)
        response = client.delete(self.URL_TMPL.format(id=999_999))
        assert response.status_code == 404
