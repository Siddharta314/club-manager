"""Tests for Idempotency-Key support on join/leave endpoints.

Mobile clients with flaky networks can retry the same mutation when
a request times out. The ``Idempotency-Key`` header lets them say
"this is the same logical request — give me the cached response
instead of re-running it."

These tests verify:
- Same key + same user + same endpoint → cached response returned
  verbatim on retry (no second mutation, no second MatchPlayer row).
- Different keys → treated as separate requests (each runs the
  mutation, each gets its own cached response).
- No key → original behaviour (no caching, no retry contract).
- Different users with the same key → independent (cache key is
  scoped per user so no cross-user collisions).
- TTL expiry → cached response falls out of the cache after
  ``IDEMPOTENCY_KEY_TTL_SECONDS`` (simulated by clearing the cache).
- Empty key + missing user → helper functions return ``None`` /
  no-op (the early-return guards).
"""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from clubs.models import Club, Court
from match_slots.models import MatchSlot
from matches.idempotency import (
    IDEMPOTENCY_HEADER,
    get_cached,
    store,
)
from matches.models import Match, MatchPlayer
from players.models import User


# ---------------------------------------------------------------------------
# Helpers + fixtures
# ---------------------------------------------------------------------------
def _make_club_court_slot() -> tuple[Club, Court, MatchSlot]:
    """Same helper pattern as the other matches view tests."""
    creator = User.objects.create(
        username="i_creator", email="i_creator@example.com"
    )
    club = Club.objects.create(name="IC", address="IC 1", created_by=creator)
    club.admins.add(creator)
    court = Court.objects.create(club=club, name="IC Court")
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
    """Wipe the cache between tests so cached responses don't leak.

    Idempotency tests are sensitive to cross-test pollution — we
    want each test to start with an empty cache.
    """
    cache.clear()
    yield
    cache.clear()


# ---------------------------------------------------------------------------
# Join + Idempotency-Key
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestJoinIdempotency:
    URL_TMPL = "/api/v1/matches/{id}/join/"
    HEADER = "HTTP_IDEMPOTENCY_KEY"

    def test_join_with_idempotency_key_does_not_double_create_membership(
        self, auth_client
    ) -> None:
        """Same key + same payload → single MatchPlayer row, cached body returned."""
        from matches.services import create_match_from_slot

        _, _, slot = _make_club_court_slot()
        client, host = auth_client("i_jh", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        client2, _ = auth_client("i_jp", level=3.40)

        first = client2.post(
            self.URL_TMPL.format(id=match.pk),
            **{self.HEADER: "join-retry-001"},
        )
        assert first.status_code == 200, first.data
        assert MatchPlayer.objects.filter(match=match).count() == 2  # host + 1

        # Retry with the same key — should NOT create a 3rd row, should
        # return the cached 200 with the same body.
        second = client2.post(
            self.URL_TMPL.format(id=match.pk),
            **{self.HEADER: "join-retry-001"},
        )
        assert second.status_code == 200
        assert MatchPlayer.objects.filter(match=match).count() == 2
        # Same body — same number of players.
        assert len(second.data["players"]) == len(first.data["players"])

    def test_join_with_different_idempotency_keys_creates_separate_rows(
        self, auth_client
    ) -> None:
        """Different keys → each request runs the mutation independently.

        Note: ``auth_client`` rebinds the global Clerk auth state, so
        we must call it immediately before each post that needs the
        corresponding user. Setting up two clients up-front and then
        alternating between them would silently send all requests as
        whichever user was bound last.
        """
        from matches.services import create_match_from_slot

        _, _, slot = _make_club_court_slot()
        _, host = auth_client("i_dh", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)

        # Bind and post as user A first.
        client_a, _ = auth_client("i_da", level=3.40)
        first = client_a.post(
            self.URL_TMPL.format(id=match.pk),
            **{self.HEADER: "key-A"},
        )
        assert first.status_code == 200

        # Now re-bind and post as user B with a different key.
        client_b, _ = auth_client("i_db", level=3.40)
        second = client_b.post(
            self.URL_TMPL.format(id=match.pk),
            **{self.HEADER: "key-B"},
        )
        assert second.status_code == 200
        assert MatchPlayer.objects.filter(match=match).count() == 3

    def test_join_without_idempotency_key_works_as_before(self, auth_client) -> None:
        """No header → no caching, every request runs through the service."""
        from matches.services import create_match_from_slot

        _, _, slot = _make_club_court_slot()
        client, host = auth_client("i_nh", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        client2, _ = auth_client("i_np", level=3.40)

        first = client2.post(self.URL_TMPL.format(id=match.pk))
        second = client2.post(self.URL_TMPL.format(id=match.pk))
        assert first.status_code == 200
        assert second.status_code == 200
        # No double-creation because the service-layer idempotency kicks in
        # for re-join — but no cache lookup should have happened.
        assert MatchPlayer.objects.filter(match=match).count() == 2


# ---------------------------------------------------------------------------
# Leave + Idempotency-Key
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestLeaveIdempotency:
    URL_TMPL = "/api/v1/matches/{id}/leave/"
    HEADER = "HTTP_IDEMPOTENCY_KEY"

    def test_leave_with_idempotency_key_returns_cached_204(self, auth_client) -> None:
        """Same key → cached 204 returned, no second leave attempt."""
        from matches.services import create_match_from_slot, join_match

        _, _, slot = _make_club_court_slot()
        _, host = auth_client("i_lh", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)

        # Bind a second player; use the same user that will leave so the
        # leave endpoint actually has a MatchPlayer row to remove.
        _, leaver = auth_client("i_lp_user", level=3.40)
        join_match(match=match, user=leaver)
        assert MatchPlayer.objects.filter(match=match).count() == 2

        # Bind + first leave via API with a key.
        client_leaver, _ = auth_client("i_lp_user", level=3.40)
        first = client_leaver.post(
            self.URL_TMPL.format(id=match.pk),
            **{self.HEADER: "leave-retry-001"},
        )
        assert first.status_code == 204
        assert MatchPlayer.objects.filter(match=match).count() == 1  # host only

        # Second leave with the same key — must return 204 (cached) and
        # must not touch the row. ``client_leaver`` is still bound to
        # ``i_lp_user`` so no re-bind needed here.
        second = client_leaver.post(
            self.URL_TMPL.format(id=match.pk),
            **{self.HEADER: "leave-retry-001"},
        )
        assert second.status_code == 204
        assert MatchPlayer.objects.filter(match=match).count() == 1


# ---------------------------------------------------------------------------
# Cross-user isolation + TTL
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestIdempotencyScoping:
    URL_TMPL = "/api/v1/matches/{id}/join/"
    HEADER = "HTTP_IDEMPOTENCY_KEY"

    def test_idempotency_key_is_scoped_per_user(self, auth_client) -> None:
        """Different users with the same key → independent cached responses."""
        from matches.services import create_match_from_slot

        _, _, slot = _make_club_court_slot()
        _, host = auth_client("i_sh", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)

        # Bind and post as user A first (same key, different user later).
        client_a, _ = auth_client("i_sa", level=3.40)
        first = client_a.post(
            self.URL_TMPL.format(id=match.pk),
            **{self.HEADER: "shared-key"},
        )
        assert first.status_code == 200

        # Re-bind as user B; same key but B must get its own response,
        # not A's cached body.
        client_b, _ = auth_client("i_sb", level=3.40)
        second = client_b.post(
            self.URL_TMPL.format(id=match.pk),
            **{self.HEADER: "shared-key"},
        )
        assert second.status_code == 200
        # Both users joined — 3 MatchPlayer rows total (host + 2).
        assert MatchPlayer.objects.filter(match=match).count() == 3

    def test_cached_response_is_returned_after_replay(self, auth_client) -> None:
        """Cached body is returned verbatim — the second response body
        matches the first one byte-for-byte (same players count, same
        host id, etc.)."""
        from matches.services import create_match_from_slot

        _, _, slot = _make_club_court_slot()
        _, host = auth_client("i_rh", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)
        client, _ = auth_client("i_rp", level=3.40)

        first = client.post(
            self.URL_TMPL.format(id=match.pk),
            **{self.HEADER: "replay-key"},
        )
        assert first.status_code == 200

        # Mutate the match state in the DB behind the API's back:
        # add an extra player directly via the ORM. The cached
        # response was computed *before* this mutation, so a retry
        # with the same key must still return the stale body.
        extra = User.objects.create(
            username="i_re", email="i_re@example.com", level=3.40
        )
        MatchPlayer.objects.create(match=match, user=extra)
        assert MatchPlayer.objects.filter(match=match).count() == 3  # host + extra + joiner

        retry = client.post(
            self.URL_TMPL.format(id=match.pk),
            **{self.HEADER: "replay-key"},
        )
        assert retry.status_code == 200
        # The cached body was computed when the count was 2 — retry
        # returns the same 2-player response, not the live 3-player one.
        assert len(retry.data["players"]) == 2

    def test_cache_clear_simulates_ttl_expiry(self, auth_client) -> None:
        """Clearing the cache is the test-harness equivalent of TTL
        expiry. After clear, the same key behaves like a fresh
        request and creates a new mutation."""
        from matches.services import create_match_from_slot

        _, _, slot = _make_club_court_slot()
        _, host = auth_client("i_th", level=3.50)
        match = create_match_from_slot(slot=slot, host=host)

        # First user joins with a key.
        client_a, _ = auth_client("i_ta", level=3.40)
        first = client_a.post(
            self.URL_TMPL.format(id=match.pk),
            **{self.HEADER: "ttl-key"},
        )
        assert first.status_code == 200

        # Simulate TTL expiry.
        cache.clear()

        # Re-bind as a second user (different User, same key). The
        # cache is empty → this is treated as a fresh request, not a
        # cached retry of the first user's response.
        client_b, _ = auth_client("i_tb", level=3.40)
        second = client_b.post(
            self.URL_TMPL.format(id=match.pk),
            **{self.HEADER: "ttl-key"},
        )
        assert second.status_code == 200
        assert MatchPlayer.objects.filter(match=match).count() == 3


# ---------------------------------------------------------------------------
# Helper-function unit tests (defensive guards)
# ---------------------------------------------------------------------------
class TestIdempotencyHelpers:
    """Direct unit tests for ``get_cached`` / ``store`` / ``IDEMPOTENCY_HEADER``.

    The view-level tests above cover the happy path; these exercise
    the helper functions in isolation so the defensive guards
    (empty key, anonymous request) stay covered even when the view
    contract already prevents them.
    """

    def test_idempotency_header_constant(self) -> None:
        assert IDEMPOTENCY_HEADER == "Idempotency-Key"

    def test_get_cached_returns_none_for_empty_key(self) -> None:
        """Empty key → early return, no cache lookup."""
        request = SimpleNamespace(path="/x/", user=SimpleNamespace(pk=42))
        assert get_cached("", request) is None

    def test_get_cached_returns_none_for_anonymous_request(self) -> None:
        """No user on the request → no scope to cache under."""
        request = SimpleNamespace(path="/x/", user=None)
        assert get_cached("some-key", request) is None

    def test_get_cached_returns_none_when_user_has_no_pk(self) -> None:
        """Anonymous-like user (no pk) → no scope to cache under."""
        request = SimpleNamespace(path="/x/", user=SimpleNamespace(pk=None))
        assert get_cached("some-key", request) is None

    def test_store_is_noop_for_empty_key(self) -> None:
        """Empty key → early return, no cache write."""
        request = SimpleNamespace(path="/x/", user=SimpleNamespace(pk=42))
        # Should not raise and should not affect the cache.
        store("", request, 200, {"ok": True})

    def test_store_is_noop_for_anonymous_request(self) -> None:
        """No user on the request → no scope to cache under."""
        request = SimpleNamespace(path="/x/", user=None)
        store("k", request, 200, {"ok": True})

    def test_store_and_get_cached_roundtrip(self) -> None:
        """Roundtrip: store writes, get_cached reads the same tuple back."""
        cache.clear()
        request = SimpleNamespace(path="/x/", user=SimpleNamespace(pk=99))
        store("rt-key", request, 201, {"detail": "created"})
        assert get_cached("rt-key", request) == (201, {"detail": "created"})