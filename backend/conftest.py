"""Top-level pytest configuration.

Pulls in `pytest-django` configuration from `pytest.ini`, exposes shared
fixtures (see per-app `tests/conftest.py` for app-specific helpers), and
configures coverage.

Shared fixtures for the auth_clerk app live here so they're visible to
all test modules (clubs, etc.) that exercise the API client.
"""
from __future__ import annotations

from typing import Any

import pytest
from clerk_backend_api.security.types import AuthStatus, RequestState


@pytest.fixture
def user_factory(db):
    """Lazy user factory using model_bakery.

    Yields a callable that accepts kwargs and returns a persisted User. Uses
    `model_bakery` rather than `factory-boy` to avoid having to declare a
    Factory class for every model — every test gets a fresh DB thanks to the
    `db` fixture.
    """
    from model_bakery import baker

    def make(**kwargs: Any):
        return baker.make("players.User", **kwargs)

    return make


# ---------------------------------------------------------------------------
# Auth-clerk shared fixtures — moved here from auth_clerk/tests/conftest.py
# so any app test that drives the API client can use them.
# ---------------------------------------------------------------------------
@pytest.fixture
def make_clerk_state():
    """Return a callable that builds a ``RequestState`` for mocking."""

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
    """Patch ``auth_clerk.middleware._verify_token`` for the duration of
    the test. The patch is bound to the test's monkeypatch so it
    auto-undoes on teardown."""

    state_holder: dict[str, Any] = {"state": None}

    def _set(state: RequestState) -> None:
        state_holder["state"] = state

    import auth_clerk.middleware as mw

    def _fake_verify(request: Any, token: str) -> RequestState:
        st = state_holder["state"]
        if st is None:
            return RequestState(status=AuthStatus.SIGNED_OUT)
        return st

    monkeypatch.setattr(mw, "_verify_token", _fake_verify)
    return _set
