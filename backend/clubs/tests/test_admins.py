"""Tests for club admin membership and creator auto-promotion.

These tests cover the M2M ``Club.admins`` relation and the
``ClubViewSet.perform_create`` auto-promotion path. Secondary admin
add/remove endpoints are covered in ``TestClubAdminEndpoints`` at the
bottom of this file (added when the endpoints land — they share the
fixtures and helpers defined above).
"""
from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from auth_clerk.authentication import ClerkSessionAuthentication
from clubs.models import Club
from players.models import User


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def auth_client(bypass_clerk_auth, make_clerk_state, db):
    """Return an APIClient bound to a Clerk-authenticated user.

    Mirrors the fixture in ``test_views.py`` — duplicated here so this
    module is self-contained.
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


@pytest.fixture
def club_with_admin(db):
    """Return a callable that creates a Club with a given creator and
    auto-adds the creator to the admins M2M.

    Mirrors what ``perform_create`` does so direct-creation tests can
    match the API-driven state.
    """

    def _make(creator: User, **kwargs) -> Club:
        club = Club.objects.create(created_by=creator, **kwargs)
        club.admins.add(creator)
        return club

    return _make


# ---------------------------------------------------------------------------
# Model: admins M2M + is_admin helper
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestClubAdminsRelation:
    """The M2M field exists and ``Club.is_admin`` honours it."""

    def test_club_has_admins_m2m_attribute(self) -> None:
        # The reverse accessor is wired under 'administered_clubs' on
        # the User side; the forward accessor is 'admins' on Club.
        assert hasattr(Club, "admins")

    def test_is_admin_returns_true_for_admin_user(
        self, club_with_admin
    ) -> None:
        from players.models import User

        creator = User.objects.create(username="c1", email="c1@example.com")
        club = club_with_admin(creator, name="A", address="Addr")
        assert club.is_admin(creator) is True

    def test_is_admin_returns_false_for_non_admin_user(
        self, club_with_admin
    ) -> None:
        from players.models import User

        creator = User.objects.create(username="c2", email="c2@example.com")
        other = User.objects.create(username="o", email="o@example.com")
        club = club_with_admin(creator, name="A", address="Addr")
        assert club.is_admin(other) is False

    def test_is_admin_returns_false_for_none(self, club_with_admin) -> None:
        from players.models import User

        creator = User.objects.create(username="c3", email="c3@example.com")
        club = club_with_admin(creator, name="A", address="Addr")
        assert club.is_admin(None) is False

    def test_is_admin_accepts_user_pk(self, club_with_admin) -> None:
        from players.models import User

        creator = User.objects.create(username="c4", email="c4@example.com")
        club = club_with_admin(creator, name="A", address="Addr")
        assert club.is_admin(creator.pk) is True
        assert club.is_admin(creator.pk + 9999) is False

    def test_admin_reverse_relation_named_administered_clubs(
        self, club_with_admin
    ) -> None:
        from players.models import User

        creator = User.objects.create(username="c5", email="c5@example.com")
        club = club_with_admin(creator, name="A", address="Addr")
        # Refresh to populate reverse cache.
        assert list(creator.administered_clubs.all()) == [club]

    def test_admins_m2m_allows_multiple_members(
        self, club_with_admin
    ) -> None:
        from players.models import User

        creator = User.objects.create(username="c6", email="c6@example.com")
        secondary = User.objects.create(username="s6", email="s6@example.com")
        club = club_with_admin(creator, name="A", address="Addr")
        club.admins.add(secondary)
        assert club.is_admin(creator) is True
        assert club.is_admin(secondary) is True


# ---------------------------------------------------------------------------
# perform_create: auto-promote creator
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestPerformCreateAutoPromote:
    """``ClubViewSet.perform_create`` must auto-add the creator to the
    admins M2M and promote their role to ``club_admin``."""

    URL = "/api/v1/clubs/"

    def test_creator_is_auto_added_to_admins(self, auth_client) -> None:
        client, user = auth_client("user_creator_m2m")
        # Sanity: pre-state is a plain player with no clubs.
        assert user.role == User.Role.PLAYER
        assert list(user.administered_clubs.all()) == []
        response = client.post(
            self.URL, {"name": "New", "address": "Addr"}, format="json"
        )
        assert response.status_code == 201, response.data
        # Creator is now an admin of the new club.
        assert response.data["admins"] == [user.pk]

    def test_creator_role_is_promoted_to_club_admin(self, auth_client) -> None:
        client, user = auth_client("user_creator_promote")
        assert user.role == User.Role.PLAYER
        client.post(self.URL, {"name": "P", "address": "P1"}, format="json")
        user.refresh_from_db()
        assert user.role == User.Role.CLUB_ADMIN

    def test_existing_club_admin_keeps_role_on_create(self, auth_client) -> None:
        # If the user already has the club_admin role (e.g. they're
        # adding a second club), perform_create should not flip them
        # back to player — and the save() call should be skipped (no
        # unnecessary DB write).
        client, user = auth_client(
            "user_already_admin", role=User.Role.CLUB_ADMIN
        )
        client.post(self.URL, {"name": "Z", "address": "Z1"}, format="json")
        user.refresh_from_db()
        assert user.role == User.Role.CLUB_ADMIN

    def test_create_response_includes_admins_list(self, auth_client) -> None:
        client, user = auth_client("user_response_shape")
        response = client.post(
            self.URL, {"name": "S", "address": "S1"}, format="json"
        )
        assert response.status_code == 201
        assert "admins" in response.data
        assert response.data["admins"] == [user.pk]

    def test_two_creators_each_own_their_admins_set(self, auth_client) -> None:
        # Each creator only sees themselves in their own club's admins
        # set — the M2M is per-club, not global. The
        # ``auth_client`` fixture patches Clerk state globally so we
        # need to call it once per test scope; this test models the
        # second creator in a separate transaction by checking the
        # DB-level isolation directly.
        client, user_one = auth_client("user_one_iso")
        r1 = client.post(
            self.URL, {"name": "C1", "address": "A1"}, format="json"
        )
        assert r1.data["admins"] == [user_one.pk]
        # Now model the second creator via a direct create with a
        # different creator; verify the first club is unaffected.
        from clubs.models import Club
        user_two = User.objects.create(
            username="user_two_iso",
            email="user_two_iso@example.com",
            clerk_user_id="user_two_iso",
        )
        club2 = Club.objects.create(
            name="C2", address="A2", created_by=user_two
        )
        club2.admins.add(user_two)
        # First club still only has user_one as admin.
        from clubs.models import Club as ClubModel

        c1_fresh = ClubModel.objects.get(pk=r1.data["id"])
        assert list(c1_fresh.admins.values_list("pk", flat=True)) == [user_one.pk]
        # Second club only has user_two.
        assert list(club2.admins.values_list("pk", flat=True)) == [user_two.pk]