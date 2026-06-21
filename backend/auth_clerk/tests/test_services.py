"""Tests for the auth_clerk service layer.

Pure-Python helpers; no middleware or webhooks involved.
"""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from auth_clerk.services import (
    apply_user_update,
    get_or_create_user_from_clerk,
    soft_delete_user,
)


pytestmark = pytest.mark.django_db


User = get_user_model()


class TestGetOrCreateUserFromClerk:
    def test_creates_new_user(self) -> None:
        user, created = get_or_create_user_from_clerk(
            clerk_user_id="svc_1",
            email="svc@example.com",
            name="Service User",
        )
        assert created is True
        assert user.email == "svc@example.com"
        assert user.username == "Service User"
        assert user.level == 3.00  # type: ignore[attr-defined]
        assert user.role == User.Role.PLAYER

    def test_returns_existing_user(self, user_factory) -> None:
        existing = user_factory(clerk_user_id="svc_2")
        user, created = get_or_create_user_from_clerk(
            clerk_user_id="svc_2",
            email="ignored@example.com",
            name="Ignored",
        )
        assert created is False
        assert user.pk == existing.pk
        # Existing email NOT overwritten (the spec only allows update on
        # user.updated).
        assert user.email == existing.email


class TestApplyUserUpdate:
    def test_updates_email(self, user_factory) -> None:
        user = user_factory(clerk_user_id="svc_3", email="old@example.com")
        apply_user_update(user, {"email": "new@example.com"})
        user.refresh_from_db()
        assert user.email == "new@example.com"

    def test_does_not_touch_role_or_club(self, user_factory) -> None:
        user = user_factory(
            clerk_user_id="svc_4",
            role=User.Role.CLUB_ADMIN,
        )
        original_role = user.role
        apply_user_update(user, {"email": "ok@example.com"})
        user.refresh_from_db()
        assert user.role == original_role
        assert user.club_id is None

    def test_does_not_touch_level(self, user_factory) -> None:
        user = user_factory(clerk_user_id="svc_5", level=4.50)  # type: ignore[attr-defined]
        apply_user_update(user, {"email": "level@example.com"})
        user.refresh_from_db()
        assert user.level == 4.50  # type: ignore[attr-defined]


class TestSoftDeleteUser:
    def test_sets_is_active_false(self, user_factory) -> None:
        user = user_factory(clerk_user_id="svc_6")
        soft_delete_user(user)
        user.refresh_from_db()
        assert user.is_active is False

    def test_idempotent_when_already_inactive(self, user_factory) -> None:
        user = user_factory(clerk_user_id="svc_7", is_active=False)
        soft_delete_user(user)  # should not raise
        user.refresh_from_db()
        assert user.is_active is False
