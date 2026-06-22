"""Tests for the chat app — DRF view layer.

Covers the HTTP layer for the polling + create endpoints:

- ``GET /api/v1/matches/{id}/messages/`` — list messages with the
  ``?since=`` cursor, 403 for outsiders, 400 for malformed ``since``.
- ``POST /api/v1/matches/{id}/messages/`` — post a message with
  participant-only access, 400 for empty / over-length text,
  Idempotency-Key support for mobile retry safety.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from chat.models import ChatMessage
from clubs.models import Club, Court
from companions.models import Companion
from match_slots.models import MatchSlot
from matches.models import Match, MatchPlayer
from matches.services import create_match_from_slot, join_match
from players.models import User


# ---------------------------------------------------------------------------
# Helpers + fixtures
# ---------------------------------------------------------------------------
def _make_club_court_slot() -> tuple[Club, Court, MatchSlot]:
    """Create a Club + Court + future MatchSlot."""
    creator = User.objects.create(
        username="cv_creator", email="cv_creator@example.com"
    )
    club = Club.objects.create(name="CV", address="CV 1", created_by=creator)
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


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear the cache between tests to prevent idempotency leaks."""
    cache.clear()
    yield
    cache.clear()


# ---------------------------------------------------------------------------
# GET — polling
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetChatMessages:
    URL_TMPL = "/api/v1/matches/{id}/messages/"

    def test_get_as_player_returns_messages(self, auth_client) -> None:
        _, _, slot = _make_club_court_slot()
        client, host = auth_client("cv_ph", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        ChatMessage.objects.create(match=match, author_user=host, text="hi")
        response = client.get(self.URL_TMPL.format(id=match.pk))
        assert response.status_code == 200, response.data
        assert len(response.data) == 1
        assert response.data[0]["text"] == "hi"
        assert response.data[0]["author_user_id"] == host.pk
        assert response.data[0]["author_display_name"] == host.email

    def test_get_as_companion_sponsor_returns_messages(self, auth_client) -> None:
        """A user who sponsors a companion on the match can read the chat
        even if they aren't a MatchPlayer themselves."""
        _, _, slot = _make_club_court_slot()
        # Host creates the match.
        _, host = auth_client("cv_sh", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        # A sponsor (not a MatchPlayer) registers a companion.
        _, sponsor = auth_client("cv_ss", level=3.50)
        companion = Companion.objects.create(
            match=match, sponsored_by=sponsor, name="Alex", level=3.0
        )
        ChatMessage.objects.create(
            match=match, author_companion=companion, text="from companion"
        )
        # Sponsor reads.
        client_sponsor, _ = auth_client("cv_ss", level=3.50)
        response = client_sponsor.get(self.URL_TMPL.format(id=match.pk))
        assert response.status_code == 200
        assert response.data[0]["author_companion_id"] == companion.pk
        assert response.data[0]["author_display_name"] == "Alex"

    def test_get_as_outsider_returns_403(self, auth_client) -> None:
        _, _, slot = _make_club_court_slot()
        _, host = auth_client("cv_oh", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        client, _ = auth_client("cv_out", level=3.50)
        response = client.get(self.URL_TMPL.format(id=match.pk))
        assert response.status_code == 403

    def test_get_unknown_match_returns_404(self, auth_client) -> None:
        client, _ = auth_client("cv_404", level=3.50)
        response = client.get(self.URL_TMPL.format(id=999_999))
        assert response.status_code == 404

    def test_get_with_since_returns_only_newer_messages(self, auth_client) -> None:
        _, _, slot = _make_club_court_slot()
        client, host = auth_client("cv_since", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        m1 = ChatMessage.objects.create(match=match, author_user=host, text="a")
        m2 = ChatMessage.objects.create(match=match, author_user=host, text="b")
        response = client.get(
            self.URL_TMPL.format(id=match.pk) + f"?since={m1.pk}"
        )
        assert response.status_code == 200
        ids = [m["id"] for m in response.data]
        assert ids == [m2.pk]

    def test_get_with_invalid_since_returns_400(self, auth_client) -> None:
        _, _, slot = _make_club_court_slot()
        client, host = auth_client("cv_isince", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        response = client.get(
            self.URL_TMPL.format(id=match.pk) + "?since=not-a-number"
        )
        assert response.status_code == 400
        assert "since" in str(response.data).lower()

    def test_get_anonymous_returns_401(self) -> None:
        _, _, slot = _make_club_court_slot()
        client = APIClient()
        # The match id doesn't matter for the auth check.
        response = client.get(self.URL_TMPL.format(id=1))
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST — create
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestPostChatMessage:
    URL_TMPL = "/api/v1/matches/{id}/messages/"

    def test_post_as_player_returns_201(self, auth_client) -> None:
        _, _, slot = _make_club_court_slot()
        client, host = auth_client("cv_p_h", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        response = client.post(
            self.URL_TMPL.format(id=match.pk),
            {"text": "hello world"},
            format="json",
        )
        assert response.status_code == 201, response.data
        assert response.data["text"] == "hello world"
        assert response.data["author_user_id"] == host.pk
        # Persistence side-effect.
        assert ChatMessage.objects.filter(match=match, author_user=host).count() == 1

    def test_post_as_companion_sponsor_returns_201(self, auth_client) -> None:
        """A sponsor of a companion can post (they're authenticated)."""
        _, _, slot = _make_club_court_slot()
        _, host = auth_client("cv_ps_h", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        _, sponsor = auth_client("cv_ps_s", level=3.50)
        Companion.objects.create(
            match=match, sponsored_by=sponsor, name="Alex", level=3.0
        )
        client, _ = auth_client("cv_ps_s", level=3.50)
        response = client.post(
            self.URL_TMPL.format(id=match.pk),
            {"text": "from sponsor"},
            format="json",
        )
        assert response.status_code == 201, response.data
        assert response.data["author_user_id"] == sponsor.pk

    def test_post_as_outsider_returns_403(self, auth_client) -> None:
        _, _, slot = _make_club_court_slot()
        _, host = auth_client("cv_po_h", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        client, _ = auth_client("cv_po_out", level=3.50)
        response = client.post(
            self.URL_TMPL.format(id=match.pk),
            {"text": "trying"},
            format="json",
        )
        assert response.status_code == 403

    def test_post_empty_text_returns_400(self, auth_client) -> None:
        _, _, slot = _make_club_court_slot()
        client, host = auth_client("cv_pe_h", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        response = client.post(
            self.URL_TMPL.format(id=match.pk),
            {"text": ""},
            format="json",
        )
        assert response.status_code == 400
        assert "text" in str(response.data).lower()

    def test_post_whitespace_only_text_returns_400(self, auth_client) -> None:
        _, _, slot = _make_club_court_slot()
        client, host = auth_client("cv_pw_h", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        response = client.post(
            self.URL_TMPL.format(id=match.pk),
            {"text": "    "},
            format="json",
        )
        assert response.status_code == 400

    def test_post_text_over_1000_chars_returns_400(self, auth_client) -> None:
        _, _, slot = _make_club_court_slot()
        client, host = auth_client("cv_p1k_h", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        response = client.post(
            self.URL_TMPL.format(id=match.pk),
            {"text": "x" * 1001},
            format="json",
        )
        assert response.status_code == 400
        assert "1000" in str(response.data)

    def test_post_unknown_match_returns_404(self, auth_client) -> None:
        client, _ = auth_client("cv_p404", level=3.50)
        response = client.post(
            self.URL_TMPL.format(id=999_999),
            {"text": "hi"},
            format="json",
        )
        assert response.status_code == 404

    def test_post_with_idempotency_key_returns_cached_on_retry(
        self, auth_client
    ) -> None:
        """Same Idempotency-Key + same user → cached 201 on retry."""
        _, _, slot = _make_club_court_slot()
        client, host = auth_client("cv_idem_h", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)

        first = client.post(
            self.URL_TMPL.format(id=match.pk),
            {"text": "first try"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="chat-retry-001",
        )
        assert first.status_code == 201
        assert ChatMessage.objects.filter(match=match).count() == 1

        # Retry with the same key — must return 201 again (cached body)
        # and NOT create a second message.
        second = client.post(
            self.URL_TMPL.format(id=match.pk),
            {"text": "should not appear"},
            format="json",
            HTTP_IDEMPOTENCY_KEY="chat-retry-001",
        )
        assert second.status_code == 201
        assert ChatMessage.objects.filter(match=match).count() == 1
        # Cached body returns the original text, not the retry's text.
        assert second.data["text"] == "first try"