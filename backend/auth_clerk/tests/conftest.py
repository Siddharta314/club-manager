"""Shared pytest fixtures for the auth_clerk app.

Provides a ``clerk_payload`` factory and a ``verified_request`` factory
that bypass the real Clerk SDK so tests can drive the middleware with
deterministic state.
"""
from __future__ import annotations

from typing import Any

import pytest
from clerk_backend_api.security.types import AuthStatus, RequestState


@pytest.fixture
def make_clerk_state():
    """Return a callable that builds a ``RequestState`` for mocking.

    The middleware reads ``status``, ``payload`` and ``reason``; tests
    monkey-patch ``_get_clerk_client`` (or ``ClerkJWTMiddleware``'s
    internal helper) to return the result of this factory.
    """

    def make(
        *,
        status: AuthStatus = AuthStatus.SIGNED_IN,
        sub: str = "user_test_abc",
        email: str = "test@example.com",
        name: str = "Test User",
        reason: Any = None,
    ) -> RequestState:
        payload: dict[str, Any] = {"sub": sub, "email": email, "name": name}
        return RequestState(
            status=status,
            reason=reason,
            token="mock.jwt.token",
            payload=payload,
        )

    return make


@pytest.fixture
def bypass_clerk_auth(monkeypatch):
    """Patch ``ClerkJWTMiddleware``'s token verifier so it returns a
    caller-supplied ``RequestState``.

    The patch lives for the duration of the test (monkeypatch is
    function-scoped) so the test can call ``bypass_clerk_auth(state)``
    once and then drive the API client.

    Usage::

        def test_x(client, bypass_clerk_auth, make_clerk_state):
            state = make_clerk_state(sub="user_x")
            bypass_clerk_auth(state)
            response = client.get("/api/v1/clubs/")
    """

    state_holder: dict[str, Any] = {"state": None}

    def _set(state: RequestState) -> None:
        state_holder["state"] = state

    # Install the patch now so it survives until the test ends.
    import auth_clerk.middleware as mw

    def _fake_verify(request: Any, token: str) -> RequestState:
        st = state_holder["state"]
        if st is None:
            # Default to signed-out so a test that forgets to set state
            # fails loudly with a 401 instead of a 200.
            return RequestState(status=AuthStatus.SIGNED_OUT)
        return st

    monkeypatch.setattr(mw, "_verify_token", _fake_verify)
    return _set
