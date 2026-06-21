"""Shared pytest fixtures for the clubs app."""
from __future__ import annotations

from datetime import time
from typing import Any

import pytest


@pytest.fixture
def club_factory(db):
    from model_bakery import baker

    def make(**kwargs: Any):
        if "created_by" not in kwargs:
            from players.models import User

            creator = User.objects.create(
                username=kwargs.pop("_username", "creator"),
                email=kwargs.pop("_email", "creator@example.com"),
            )
            kwargs["created_by"] = creator
        return baker.make("clubs.Club", **kwargs)

    return make


@pytest.fixture
def court_factory(club_factory):
    from model_bakery import baker

    def make(club: Any | None = None, **kwargs: Any) -> Any:
        if club is None:
            club = club_factory()
        return baker.make("clubs.Court", club=club, **kwargs)

    return make


@pytest.fixture
def schedule_factory(court_factory):
    from model_bakery import baker

    def make(court: Any | None = None, **kwargs: Any) -> Any:
        if court is None:
            court = court_factory()
        kwargs.setdefault("weekday", 0)
        kwargs.setdefault("start_time", time(17, 0))
        kwargs.setdefault("end_time", time(21, 0))
        kwargs.setdefault("duration_minutes", 60)
        return baker.make("clubs.Schedule", court=court, **kwargs)

    return make


@pytest.fixture
def club_admin(user_factory) -> Any:
    """User with role=club_admin and a freshly created club."""
    from clubs.models import Club
    from players.models import User

    user = user_factory()
    user.role = User.Role.CLUB_ADMIN
    user.save(update_fields=["role"])
    club = Club.objects.create(name="Admin Club", address="Admin 1", created_by=user)
    user.club = club
    user.save(update_fields=["club"])
    return user


@pytest.fixture
def club_player(user_factory) -> Any:
    """Plain authenticated user (role=player, no club)."""
    return user_factory()
