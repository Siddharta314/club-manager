"""Tests for the ``promote_superadmin`` management command.

Covers:
- Promotes a fresh Clerk user to super_admin with admin flags.
- Promotes an existing User (idempotent — no-op when already set).
- Errors when the clerk_user_id argument is missing (shouldn't happen
  via the parser, but exercise the explicit guard).
"""
from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from io import StringIO

pytestmark = pytest.mark.django_db


User = get_user_model()


def _capture(cmd: str, *args: str, **kwargs: Any) -> tuple[str, str]:
    out, err = StringIO(), StringIO()
    call_command(cmd, *args, stdout=out, stderr=err, **kwargs)
    return out.getvalue(), err.getvalue()


class TestPromoteSuperadmin:
    def test_creates_user_when_missing(self) -> None:
        out, _ = _capture(
            "promote_superadmin",
            "user_super_1",
            email="super@example.com",
            name="Super Admin",
        )
        user = User.objects.get(clerk_user_id="user_super_1")
        assert user.role == User.Role.SUPER_ADMIN
        assert user.is_staff is True
        assert user.is_superuser is True
        assert user.email == "super@example.com"
        assert "Promoted" in out

    def test_promotes_existing_user(self, user_factory) -> None:
        existing = user_factory(clerk_user_id="user_super_2")
        _capture("promote_superadmin", "user_super_2")
        existing.refresh_from_db()
        assert existing.role == User.Role.SUPER_ADMIN
        assert existing.is_staff is True
        assert existing.is_superuser is True

    def test_idempotent_when_already_super_admin(self, user_factory) -> None:
        existing = user_factory(
            clerk_user_id="user_super_3",
            role=User.Role.SUPER_ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        out, _ = _capture("promote_superadmin", "user_super_3")
        existing.refresh_from_db()
        assert existing.role == User.Role.SUPER_ADMIN
        assert "already" in out.lower()

    def test_empty_clerk_user_id_raises(self) -> None:
        with pytest.raises(CommandError):
            call_command("promote_superadmin", "")
