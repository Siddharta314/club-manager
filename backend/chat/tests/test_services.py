"""Tests for the chat app — service-layer business logic.

Covers:

- ``user_can_access_match_chat`` — the participant-only access gate
  (player on the match → True, sponsor of a companion on the match
  → True, otherwise → False).
- ``list_messages`` — pagination by id, default ordering (asc), the
  ``limit`` cap.
- ``post_message`` — XOR author enforcement and persistence.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from chat.models import ChatMessage
from chat.services import (
    list_messages,
    post_message,
    user_can_access_match_chat,
)
from clubs.models import Club, Court
from companions.models import Companion
from match_slots.models import MatchSlot
from matches.models import Match, MatchPlayer
from players.models import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_match(db) -> tuple[Match, User, User, User]:
    """Create a club + court + future slot + match + host.

    Returns ``(match, host, outsider, sponsor)`` so each test has
    the full cast it needs without repeating setup.
    """
    creator = User.objects.create(
        username="cs_creator", email="cs_creator@example.com"
    )
    club = Club.objects.create(name="CS", address="CS 1", created_by=creator)
    court = Court.objects.create(club=club, name="CS Court")
    start = timezone.now() + timedelta(hours=1)
    slot = MatchSlot.objects.create(
        court=court,
        start_time=start,
        end_time=start + timedelta(minutes=90),
    )
    host = User.objects.create(username="cs_host", email="cs_host@example.com")
    outsider = User.objects.create(
        username="cs_out", email="cs_out@example.com"
    )
    sponsor = User.objects.create(
        username="cs_sponsor", email="cs_sponsor@example.com"
    )
    match = Match.objects.create(host=host)
    slot.booked_match = match
    slot.save()
    MatchPlayer.objects.create(match=match, user=host)
    return match, host, outsider, sponsor


# ---------------------------------------------------------------------------
# user_can_access_match_chat
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUserCanAccessMatchChat:
    def test_player_on_match_returns_true(self) -> None:
        match, host, _, _ = _make_match(None)
        assert user_can_access_match_chat(host, match) is True

    def test_sponsor_of_companion_returns_true(self) -> None:
        match, _, _, sponsor = _make_match(None)
        # ``sponsor`` is not a MatchPlayer but registers a companion.
        Companion.objects.create(
            match=match, sponsored_by=sponsor, name="Alex", level=3.0
        )
        assert user_can_access_match_chat(sponsor, match) is True

    def test_outsider_returns_false(self) -> None:
        match, _, outsider, _ = _make_match(None)
        assert user_can_access_match_chat(outsider, match) is False

    def test_anonymous_user_returns_false(self) -> None:
        match, _, _, _ = _make_match(None)
        assert user_can_access_match_chat(None, match) is False

    def test_user_without_pk_returns_false(self) -> None:
        from types import SimpleNamespace

        match, _, _, _ = _make_match(None)
        # Simulate a partially-built user (e.g. ``pk`` unset).
        user = SimpleNamespace(is_authenticated=True, pk=None)
        assert user_can_access_match_chat(user, match) is False

    def test_unauthenticated_user_returns_false(self) -> None:
        from types import SimpleNamespace

        match, _, _, _ = _make_match(None)
        # AnonymousUser-style flags: not authenticated, no pk.
        user = SimpleNamespace(is_authenticated=False, pk=None)
        assert user_can_access_match_chat(user, match) is False


# ---------------------------------------------------------------------------
# list_messages
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestListMessages:
    def test_returns_messages_ordered_ascending_by_id(self) -> None:
        match, host, _, _ = _make_match(None)
        m1 = ChatMessage.objects.create(match=match, author_user=host, text="a")
        m2 = ChatMessage.objects.create(match=match, author_user=host, text="b")
        m3 = ChatMessage.objects.create(match=match, author_user=host, text="c")
        messages = list_messages(match)
        assert [m.pk for m in messages] == [m1.pk, m2.pk, m3.pk]

    def test_since_filters_to_strictly_greater_ids(self) -> None:
        match, host, _, _ = _make_match(None)
        m1 = ChatMessage.objects.create(match=match, author_user=host, text="a")
        m2 = ChatMessage.objects.create(match=match, author_user=host, text="b")
        m3 = ChatMessage.objects.create(match=match, author_user=host, text="c")
        messages = list_messages(match, since_id=m2.pk)
        assert [m.pk for m in messages] == [m3.pk]
        # m1 must be excluded (id <= since), m2 excluded (id == since).
        assert m1.pk not in [m.pk for m in messages]

    def test_since_none_returns_all(self) -> None:
        match, host, _, _ = _make_match(None)
        ChatMessage.objects.create(match=match, author_user=host, text="x")
        ChatMessage.objects.create(match=match, author_user=host, text="y")
        messages = list_messages(match, since_id=None)
        assert len(messages) == 2

    def test_limit_caps_response(self) -> None:
        match, host, _, _ = _make_match(None)
        for i in range(5):
            ChatMessage.objects.create(match=match, author_user=host, text=f"m{i}")
        messages = list_messages(match, limit=3)
        assert len(messages) == 3

    def test_empty_match_returns_empty_list(self) -> None:
        match, _, _, _ = _make_match(None)
        assert list_messages(match) == []


# ---------------------------------------------------------------------------
# post_message
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestPostMessage:
    def test_post_as_user_persists_message(self) -> None:
        match, host, _, _ = _make_match(None)
        msg = post_message(match, author_user=host, text="hello")
        assert msg.pk is not None
        assert msg.match_id == match.pk
        assert msg.author_user_id == host.pk
        assert msg.author_companion_id is None
        assert msg.text == "hello"

    def test_post_as_companion_persists_message(self) -> None:
        match, host, _, _ = _make_match(None)
        companion = Companion.objects.create(
            match=match, sponsored_by=host, name="Alex", level=3.0
        )
        msg = post_message(match, author_companion=companion, text="from companion")
        assert msg.author_user_id is None
        assert msg.author_companion_id == companion.pk

    def test_post_with_no_author_raises(self) -> None:
        match, host, _, _ = _make_match(None)
        with pytest.raises(ValueError):
            post_message(match, text="orphan")

    def test_post_with_both_authors_raises(self) -> None:
        match, host, _, _ = _make_match(None)
        companion = Companion.objects.create(
            match=match, sponsored_by=host, name="Alex", level=3.0
        )
        with pytest.raises(ValueError):
            post_message(
                match,
                author_user=host,
                author_companion=companion,
                text="both",
            )