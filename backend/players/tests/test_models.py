"""Tests for the `players.User` model.

Covers the defaults, the Clerk integration invariant, and the level/club
relationship wiring. Business logic (level matching, capacity, etc.) lives
in `matches.services` and is tested there.
"""
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from players.models import User


@pytest.mark.django_db
class TestUserDefaults:
    def test_default_level_is_three_point_zero(self):
        user = User.objects.create(username="alice", email="alice@example.com")
        assert user.level == Decimal("3.00")

    def test_default_role_is_player(self):
        user = User.objects.create(username="bob", email="b@example.com")
        assert user.role == User.Role.PLAYER

    def test_default_notification_opt_ins_are_true(self):
        user = User.objects.create(username="carol", email="c@example.com")
        assert user.notify_push is True
        assert user.notify_email is True

    def test_default_push_token_is_empty_string(self):
        user = User.objects.create(username="dave", email="d@example.com")
        assert user.push_token == ""

    def test_club_attribute_is_added_by_clubs_app(self):
        """The `club` FK ships alongside the clubs app in this PR."""
        user = User.objects.create(username="uclub", email="uclub@example.com")
        assert user.club is None

    def test_user_can_be_linked_to_a_club(self):
        from clubs.models import Club

        creator = User.objects.create(username="creator2", email="c2@example.com")
        club = Club.objects.create(
            name="Linked Club", address="Linked 1", created_by=creator
        )
        member = User.objects.create(
            username="member", email="member@example.com", club=club
        )
        member.refresh_from_db()
        assert member.club == club
        assert member in club.members.all()


@pytest.mark.django_db
class TestUserClerkIntegration:
    def test_clerk_user_id_is_unique(self):
        User.objects.create(
            username="u1",
            email="u1@example.com",
            clerk_user_id="clerk_abc123",
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            User.objects.create(
                username="u2",
                email="u2@example.com",
                clerk_user_id="clerk_abc123",
            )

    def test_clerk_user_id_can_be_empty_distinct_from_none(self):
        user = User.objects.create(
            username="u3",
            email="u3@example.com",
            clerk_user_id="",
        )
        assert user.clerk_user_id == ""


@pytest.mark.django_db
class TestUserRoleHelpers:
    def test_is_club_admin_property(self):
        admin = User.objects.create(
            username="admin", email="admin@example.com", role=User.Role.CLUB_ADMIN
        )
        player = User.objects.create(username="player", email="p@example.com")
        assert admin.is_club_admin is True
        assert player.is_club_admin is False

    def test_is_super_admin_property(self):
        sa = User.objects.create(
            username="sa", email="sa@example.com", role=User.Role.SUPER_ADMIN
        )
        assert sa.is_super_admin is True
        assert User.objects.create(username="p2", email="p2@example.com").is_super_admin is False


@pytest.mark.django_db
class TestUserLevel:
    def test_explicit_level_is_persisted(self):
        user = User.objects.create(
            username="l1", email="l1@example.com", level=Decimal("4.25")
        )
        user.refresh_from_db()
        assert user.level == Decimal("4.25")

    def test_level_field_rejects_out_of_range_via_validators(self):
        from django.core.exceptions import ValidationError

        user = User(level=Decimal("8.50"))
        with pytest.raises(ValidationError):
            user.full_clean()