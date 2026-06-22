"""Tests for the matches app — DRF views.

Covers the HTTP layer for the match lifecycle endpoints:

- ``POST /api/v1/slots/{slot_id}/match/`` — create match from slot.
- ``GET  /api/v1/matches/{id}/`` — match detail.
- ``POST /api/v1/matches/{id}/join/`` — self-signup.
- ``POST /api/v1/matches/{id}/leave/`` — leave match.
- ``POST /api/v1/matches/{id}/cancel/`` — admin cancel.
- ``POST /api/v1/matches/{id}/override-add/`` — admin override-add.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from clubs.models import Club, Court
from match_slots.models import MatchSlot
from matches.models import Match
from players.models import User


# ---------------------------------------------------------------------------
# Helpers + fixtures
# ---------------------------------------------------------------------------
def _make_club_court_slot(
    start_offset_minutes: int = 60,
) -> tuple[Club, Court, MatchSlot]:
    """Create a Club + Court + future MatchSlot for view tests.

    The Club is set up with a creator that's added to its admins
    M2M so the IsClubAdmin M2M-based check passes for admin
    endpoints.
    """
    creator = User.objects.create(
        username="m_creator", email="m_creator@example.com"
    )
    club = Club.objects.create(name="MV", address="MV 1", created_by=creator)
    club.admins.add(creator)
    court = Court.objects.create(club=club, name="MV Court")
    start = timezone.now() + timedelta(minutes=start_offset_minutes)
    slot = MatchSlot.objects.create(
        court=court,
        start_time=start,
        end_time=start + timedelta(minutes=90),
    )
    return club, court, slot


@pytest.fixture
def auth_client(bypass_clerk_auth, make_clerk_state, db):
    """APIClient bound to a Clerk-authenticated user.

    Mirrors the fixture in clubs/tests/test_views.py — duplicated
    here so the matches test module is self-contained.
    """

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
# CreateMatchFromSlotView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCreateMatchFromSlotView:
    URL_TMPL = "/api/v1/slots/{slot_id}/match/"

    def test_first_signup_creates_match_and_host(self, auth_client) -> None:
        _, _, slot = _make_club_court_slot()
        client, user = auth_client("m_host", level=3.50)
        response = client.post(self.URL_TMPL.format(slot_id=slot.pk))
        assert response.status_code == 201, response.data
        match = Match.objects.get(pk=response.data["id"])
        assert match.host_id == user.pk
        # Range = 3.50 ± 0.25
        assert float(match.level_min) == 3.25
        assert float(match.level_max) == 3.75

    def test_already_booked_slot_returns_400(self, auth_client) -> None:
        _, _, slot = _make_club_court_slot()
        client, user = auth_client("m_host2", level=3.50)
        # First call succeeds.
        response = client.post(self.URL_TMPL.format(slot_id=slot.pk))
        assert response.status_code == 201
        # Second call on the same slot fails.
        response = client.post(self.URL_TMPL.format(slot_id=slot.pk))
        assert response.status_code == 400
        assert "booked" in str(response.data).lower()

    def test_past_slot_returns_400(self, auth_client) -> None:
        # Create a slot in the past directly.
        _, court, _ = _make_club_court_slot()
        past_start = timezone.now() - timedelta(hours=2)
        slot = MatchSlot.objects.create(
            court=court,
            start_time=past_start,
            end_time=past_start + timedelta(minutes=60),
        )
        client, _ = auth_client("m_late", level=3.50)
        response = client.post(self.URL_TMPL.format(slot_id=slot.pk))
        assert response.status_code == 400
        assert "passed" in str(response.data).lower()

    def test_unknown_slot_returns_404(self, auth_client) -> None:
        client, _ = auth_client("m_404", level=3.50)
        response = client.post(self.URL_TMPL.format(slot_id=999_999))
        assert response.status_code == 404

    def test_anonymous_user_returns_401(self) -> None:
        _, _, slot = _make_club_court_slot()
        client = APIClient()
        response = client.post(self.URL_TMPL.format(slot_id=slot.pk))
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# MatchDetailView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestMatchDetailView:
    URL_TMPL = "/api/v1/matches/{id}/"

    def test_returns_match_with_players_and_companions_and_capacity(
        self, auth_client
    ) -> None:
        from companions.models import Companion
        from matches.services import create_match_from_slot

        _, _, slot = _make_club_court_slot()
        client, host = auth_client("m_det", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        Companion.objects.create(
            match=match, sponsored_by=host, name="Alex", level=3.40
        )
        response = client.get(self.URL_TMPL.format(id=match.pk))
        assert response.status_code == 200, response.data
        # Players: just the host.
        assert len(response.data["players"]) == 1
        # Companions: one.
        assert len(response.data["companions"]) == 1
        # Capacity totals.
        assert response.data["capacity"]["player_count"] == 1
        assert response.data["capacity"]["companion_count"] == 1
        assert response.data["capacity"]["total"] == 2
        assert response.data["capacity"]["is_full"] is False

    def test_unknown_match_returns_404(self, auth_client) -> None:
        client, _ = auth_client("m_det_404", level=3.50)
        response = client.get(self.URL_TMPL.format(id=999_999))
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# JoinMatchView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestJoinMatchView:
    URL_TMPL = "/api/v1/matches/{id}/join/"

    def test_join_in_range_returns_200(self, auth_client) -> None:
        from matches.services import create_match_from_slot

        _, _, slot = _make_club_court_slot()
        client, host = auth_client("m_jh", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        client2, _ = auth_client("m_jp", level=3.40)
        response = client2.post(self.URL_TMPL.format(id=match.pk))
        assert response.status_code == 200, response.data
        assert len(response.data["players"]) == 2

    def test_join_out_of_range_returns_400(self, auth_client) -> None:
        from matches.services import create_match_from_slot

        _, _, slot = _make_club_court_slot()
        client, host = auth_client("m_jo_h", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        client2, _ = auth_client("m_jo_p", level=4.50)
        response = client2.post(self.URL_TMPL.format(id=match.pk))
        assert response.status_code == 400
        assert "out of range" in str(response.data).lower()

    def test_join_cancelled_match_returns_400(self, auth_client) -> None:
        from matches.services import create_match_from_slot

        _, _, slot = _make_club_court_slot()
        client, host = auth_client("m_jc_h", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        match.is_cancelled = True
        match.save()
        client2, _ = auth_client("m_jc_p", level=3.50)
        response = client2.post(self.URL_TMPL.format(id=match.pk))
        assert response.status_code == 400
        assert "cancelled" in str(response.data).lower()

    def test_join_unknown_match_returns_404(self, auth_client) -> None:
        client, _ = auth_client("m_ju", level=3.50)
        response = client.post(self.URL_TMPL.format(id=999_999))
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# LeaveMatchView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestLeaveMatchView:
    URL_TMPL = "/api/v1/matches/{id}/leave/"

    def test_leave_returns_204(self, auth_client) -> None:
        from matches.services import create_match_from_slot, join_match

        _, _, slot = _make_club_court_slot()
        # Host signs up via the API so the match gets created with
        # the right level range.
        client, host = auth_client("m_lh", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        # Second player joins via the service so the test doesn't
        # depend on the level-range check.
        other = User.objects.create(
            username="m_lp", email="m_lp@example.com", level=3.40
        )
        join_match(match=match, user=other)
        # The second player calls leave. auth_client patches Clerk
        # state globally per test so we can only switch "users" by
        # calling auth_client again — but that re-binds a different
        # user. To exercise the leave path for `other`, we use a
        # third-user that the second call switches to.
        client_other, other_user = auth_client("m_lp_user", level=3.40)
        join_match(match=match, user=other_user)
        response = client_other.post(self.URL_TMPL.format(id=match.pk))
        assert response.status_code == 204

    def test_leave_host_returns_400(self, auth_client) -> None:
        from matches.services import create_match_from_slot

        _, _, slot = _make_club_court_slot()
        client, host = auth_client("m_lh2", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        response = client.post(self.URL_TMPL.format(id=match.pk))
        assert response.status_code == 400
        assert "host" in str(response.data).lower()

    def test_leave_unknown_match_returns_404(self, auth_client) -> None:
        client, _ = auth_client("m_lu", level=3.50)
        response = client.post(self.URL_TMPL.format(id=999_999))
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# CancelMatchView + AdminAddPlayerView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestAdminMatchActions:
    def test_cancel_by_admin(self, auth_client) -> None:
        from matches.services import create_match_from_slot

        club, _, slot = _make_club_court_slot()
        # The auth_client user becomes a club admin of a NEW club so
        # they have admin rights on it.
        client, admin = auth_client("m_adm", role=User.Role.CLUB_ADMIN)
        new_club = Club.objects.create(name="MX", address="MX 1", created_by=admin)
        new_club.admins.add(admin)
        # Create the match on the new club's slot.
        from clubs.models import Court as _Court

        new_court = _Court.objects.create(club=new_club, name="MX Court")
        start = timezone.now() + timedelta(hours=1)
        new_slot = MatchSlot.objects.create(
            court=new_court,
            start_time=start,
            end_time=start + timedelta(minutes=90),
        )
        host = User.objects.create(
            username="m_ch", email="m_ch@example.com"
        )
        match = create_match_from_slot(slot=new_slot, host=host)
        response = client.post(f"/api/v1/matches/{match.pk}/cancel/")
        assert response.status_code == 200, response.data
        match.refresh_from_db()
        assert match.is_cancelled is True

    def test_cancel_by_non_admin_returns_403(self, auth_client) -> None:
        from matches.services import create_match_from_slot

        _, _, slot = _make_club_court_slot()
        # Player (not admin) tries to cancel the match.
        client, _ = auth_client("m_chn", level=3.50)
        host = User.objects.create(
            username="m_ch2", email="m_ch2@example.com"
        )
        match = create_match_from_slot(slot=slot, host=host)
        response = client.post(f"/api/v1/matches/{match.pk}/cancel/")
        assert response.status_code == 403

    def test_override_add_by_admin_accepts_out_of_range(
        self, auth_client
    ) -> None:
        from matches.services import create_match_from_slot

        # Create a match on a fresh club the admin owns.
        client, admin = auth_client("m_oa", role=User.Role.CLUB_ADMIN)
        new_club = Club.objects.create(name="MZ", address="MZ 1", created_by=admin)
        new_club.admins.add(admin)
        from clubs.models import Court as _Court

        new_court = _Court.objects.create(club=new_club, name="MZ Court")
        start = timezone.now() + timedelta(hours=1)
        new_slot = MatchSlot.objects.create(
            court=new_court,
            start_time=start,
            end_time=start + timedelta(minutes=90),
        )
        host = User.objects.create(
            username="m_oh", email="m_oh@example.com", level=3.50
        )
        match = create_match_from_slot(slot=new_slot, host=host)
        # Out-of-range user.
        target = User.objects.create(
            username="m_ot", email="m_ot@example.com", level=5.00
        )
        response = client.post(
            f"/api/v1/matches/{match.pk}/override-add/",
            {"user_id": target.pk},
            format="json",
        )
        assert response.status_code == 200, response.data
        assert match.players.filter(user=target).exists()

    def test_override_add_by_non_admin_returns_403(self, auth_client) -> None:
        from matches.services import create_match_from_slot

        _, _, slot = _make_club_court_slot()
        client, _ = auth_client("m_oa_p", level=3.50)
        host = User.objects.create(
            username="m_oa_h", email="m_oa_h@example.com"
        )
        match = create_match_from_slot(slot=slot, host=host)
        target = User.objects.create(
            username="m_oa_t", email="m_oa_t@example.com"
        )
        response = client.post(
            f"/api/v1/matches/{match.pk}/override-add/",
            {"user_id": target.pk},
            format="json",
        )
        assert response.status_code == 403

    def test_override_add_missing_user_id_returns_400(self, auth_client) -> None:
        from matches.services import create_match_from_slot

        client, admin = auth_client("m_oam", role=User.Role.CLUB_ADMIN)
        new_club = Club.objects.create(name="MW", address="MW 1", created_by=admin)
        new_club.admins.add(admin)
        from clubs.models import Court as _Court

        new_court = _Court.objects.create(club=new_club, name="MW Court")
        start = timezone.now() + timedelta(hours=1)
        new_slot = MatchSlot.objects.create(
            court=new_court,
            start_time=start,
            end_time=start + timedelta(minutes=90),
        )
        host = User.objects.create(
            username="m_omh", email="m_omh@example.com"
        )
        match = create_match_from_slot(slot=new_slot, host=host)
        response = client.post(
            f"/api/v1/matches/{match.pk}/override-add/",
            {},
            format="json",
        )
        assert response.status_code == 400
        assert "user_id" in str(response.data).lower()
