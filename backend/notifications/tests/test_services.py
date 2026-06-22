"""Tests for the notifications app — service-layer enqueue helpers.

Covers the three enqueue_* functions:

- ``enqueue_match_created`` — fans out to subscribed members of the
  match's club (excluding the host), one Q2 task per recipient.
- ``enqueue_player_joined`` — fans out to other players on the
  match (excludes the joining user).
- ``enqueue_player_left`` — fans out to remaining players on the
  match (excludes the leaving user).

We mock ``send_notification.delay`` at the module boundary so the
tests assert the right ``(user_id, event_type, payload)`` calls fire
without requiring a live Q2 broker.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from clubs.models import Club, Court
from match_slots.models import MatchSlot
from matches.models import Match, MatchPlayer
from matches.services import create_match_from_slot, join_match
from notifications.services import (
    enqueue_match_created,
    enqueue_player_joined,
    enqueue_player_left,
)
from players.models import User


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def patched_send_delay(monkeypatch):
    """Patch ``notifications.tasks.send_notification.delay`` and yield
    the mock so tests can inspect what was queued."""
    mock = MagicMock()
    # Import lazily so we patch the symbol actually used by the
    # ``services`` module (which itself imports from tasks at call
    # time, hence the lazy import in services.py).
    import notifications.tasks as tasks_module

    monkeypatch.setattr(tasks_module, "send_notification", mock)
    # Re-bind the mock on the services module since the services
    # function does ``from notifications.tasks import send_notification``
    # inside the body — patching tasks_module is sufficient because
    # the import resolves through it.
    return mock


def _make_club_with_members(member_count: int = 2) -> tuple[Club, list[User]]:
    """Create a club with ``member_count`` members (each linked via ``User.club``).

    The creator is auto-included. Returns ``(club, members)``.
    """
    creator = User.objects.create(
        username="nc_creator", email="nc_creator@example.com"
    )
    club = Club.objects.create(name="NC", address="NC 1", created_by=creator)
    creator.club = club
    creator.save(update_fields=["club"])
    members = [creator]
    for i in range(member_count - 1):
        u = User.objects.create(
            username=f"nc_m{i}",
            email=f"nc_m{i}@example.com",
            notify_push=True,
            notify_email=True,
        )
        u.club = club
        u.save(update_fields=["club"])
        members.append(u)
    return club, members


def _make_match_with_court(club: Club, host: User) -> tuple[Match, MatchSlot]:
    """Create a future MatchSlot on ``club``'s first court + a match.

    Uses the service layer so the Match ↔ Slot ↔ MatchPlayer wiring
    is realistic.
    """
    court = Court.objects.create(club=club, name=f"{club.name} Court")
    start = timezone.now() + timedelta(hours=1)
    slot = MatchSlot.objects.create(
        court=court,
        start_time=start,
        end_time=start + timedelta(minutes=90),
    )
    match = create_match_from_slot(slot=slot, host=host)
    return match, slot


# ---------------------------------------------------------------------------
# enqueue_match_created
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestEnqueueMatchCreated:
    def test_queues_one_task_per_subscribed_member_excluding_host(
        self, patched_send_delay
    ) -> None:
        club, members = _make_club_with_members(member_count=3)
        host = members[0]
        match, _ = _make_match_with_court(club, host)

        enqueue_match_created(match.pk)

        # 3 members, 1 is host → 2 notifications.
        assert patched_send_delay.delay.call_count == 2
        called_user_ids = {
            call.kwargs["user_id"]
            for call in patched_send_delay.delay.call_args_list
        }
        assert called_user_ids == {members[1].pk, members[2].pk}

    def test_event_type_is_match_created(self, patched_send_delay) -> None:
        club, members = _make_club_with_members(member_count=2)
        host = members[0]
        match, _ = _make_match_with_court(club, host)
        enqueue_match_created(match.pk)
        for call in patched_send_delay.delay.call_args_list:
            assert call.kwargs["event_type"] == "match_created"

    def test_payload_contains_match_and_club_metadata(
        self, patched_send_delay
    ) -> None:
        club, members = _make_club_with_members(member_count=2)
        host = members[0]
        match, _ = _make_match_with_court(club, host)
        enqueue_match_created(match.pk)
        payload = patched_send_delay.delay.call_args_list[0].kwargs["payload"]
        assert payload["match_id"] == match.pk
        assert payload["club_id"] == club.pk
        assert payload["court_name"] == f"{club.name} Court"
        assert "start_time" in payload

    def test_skips_members_with_no_notification_opt_in(
        self, patched_send_delay
    ) -> None:
        """A user with both notify_push=False AND notify_email=False
        should be excluded from the fan-out."""
        club, members = _make_club_with_members(member_count=3)
        host = members[0]
        # Second member opts out of both channels.
        members[1].notify_push = False
        members[1].notify_email = False
        members[1].save(update_fields=["notify_push", "notify_email"])
        match, _ = _make_match_with_court(club, host)

        enqueue_match_created(match.pk)
        called_user_ids = {
            call.kwargs["user_id"]
            for call in patched_send_delay.delay.call_args_list
        }
        # Only the third member is subscribed (host excluded).
        assert called_user_ids == {members[2].pk}


# ---------------------------------------------------------------------------
# enqueue_player_joined
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestEnqueuePlayerJoined:
    def test_queues_to_other_players_excluding_joiner(
        self, patched_send_delay
    ) -> None:
        club, members = _make_club_with_members(member_count=3)
        host = members[0]
        match, _ = _make_match_with_court(club, host)
        # Add a second player directly (skip the level-range check).
        join_match(match=match, user=members[1], force=True)
        # Reset the mock so the join-time ``match_created`` /
        # ``player_joined`` calls don't pollute the count.
        patched_send_delay.reset_mock()

        enqueue_player_joined(match.pk, joining_user_id=members[2].pk)
        # Other players on the match: host + members[1]. Excludes members[2].
        assert patched_send_delay.delay.call_count == 2
        called_user_ids = {
            call.kwargs["user_id"]
            for call in patched_send_delay.delay.call_args_list
        }
        assert called_user_ids == {host.pk, members[1].pk}

    def test_event_type_is_player_joined(self, patched_send_delay) -> None:
        club, members = _make_club_with_members(member_count=2)
        host = members[0]
        match, _ = _make_match_with_court(club, host)
        patched_send_delay.reset_mock()

        enqueue_player_joined(match.pk, joining_user_id=members[1].pk)
        assert patched_send_delay.delay.call_args.kwargs["event_type"] == "player_joined"

    def test_payload_includes_joining_user_name(self, patched_send_delay) -> None:
        club, members = _make_club_with_members(member_count=2)
        host = members[0]
        match, _ = _make_match_with_court(club, host)
        patched_send_delay.reset_mock()
        joining = members[1]
        joining.first_name = "Alex"
        joining.last_name = "García"
        joining.save()

        enqueue_player_joined(match.pk, joining_user_id=joining.pk)
        payload = patched_send_delay.delay.call_args.kwargs["payload"]
        assert payload["joining_user_id"] == joining.pk
        assert "Alex" in payload["joining_user_name"]


# ---------------------------------------------------------------------------
# enqueue_player_left
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestEnqueuePlayerLeft:
    def test_queues_to_remaining_players_excluding_leaver(
        self, patched_send_delay
    ) -> None:
        club, members = _make_club_with_members(member_count=3)
        host = members[0]
        match, _ = _make_match_with_court(club, host)
        # Add members[1] and members[2] as players.
        join_match(match=match, user=members[1], force=True)
        join_match(match=match, user=members[2], force=True)
        patched_send_delay.reset_mock()

        enqueue_player_left(match.pk, leaving_user_id=members[1].pk)
        # Remaining players (host + members[2]) get notified.
        assert patched_send_delay.delay.call_count == 2
        called_user_ids = {
            call.kwargs["user_id"]
            for call in patched_send_delay.delay.call_args_list
        }
        assert called_user_ids == {host.pk, members[2].pk}

    def test_event_type_is_player_left(self, patched_send_delay) -> None:
        club, members = _make_club_with_members(member_count=2)
        host = members[0]
        match, _ = _make_match_with_court(club, host)
        join_match(match=match, user=members[1], force=True)
        patched_send_delay.reset_mock()

        enqueue_player_left(match.pk, leaving_user_id=members[1].pk)
        assert patched_send_delay.delay.call_args.kwargs["event_type"] == "player_left"

    def test_no_other_players_no_calls(self, patched_send_delay) -> None:
        """If only the host is on the match and the host is the one
        leaving, no fan-out (the host is excluded)."""
        club, members = _make_club_with_members(member_count=2)
        host = members[0]
        match, _ = _make_match_with_court(club, host)
        patched_send_delay.reset_mock()

        # Host is the one leaving — there are no other players to notify.
        enqueue_player_left(match.pk, leaving_user_id=host.pk)
        patched_send_delay.delay.assert_not_called()