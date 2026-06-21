"""Tests for the ClerkJWT middleware.

We bypass the real Clerk SDK via ``bypass_clerk_auth`` (see conftest)
so tests run offline and deterministic. The contract under test:

- Missing / malformed ``Authorization`` header → 401 JSON.
- Clerk ``SIGNED_OUT`` → 401 JSON with reason surfaced.
- Clerk ``SIGNED_IN`` → ``request.user`` resolves to the matching
  Django User (auto-created on first sign-in).
- Webhook, admin, static, media, and ``/_health/`` paths skip auth.
"""
from __future__ import annotations

from typing import Any

import pytest
from clerk_backend_api.security.types import AuthStatus, RequestState
from django.test import RequestFactory
from django.urls import reverse

from auth_clerk.middleware import ClerkJWTMiddleware


pytestmark = pytest.mark.django_db


def _get_response_stub(_request: Any):
    """Minimal ``get_response`` stand-in that records that it was called."""

    def get_response(request):
        request._middleware_called = True  # type: ignore[attr-defined]
        from django.http import HttpResponse

        return HttpResponse("ok", status=200)

    return get_response


def _bearer(value: str) -> dict[str, str]:
    return {"HTTP_AUTHORIZATION": value}


class TestClerkJWTMiddlewareDirect:
    """Drive the middleware directly with a ``RequestFactory``."""

    def _make_middleware(self) -> ClerkJWTMiddleware:
        return ClerkJWTMiddleware(_get_response_stub(None))

    def test_missing_authorization_header_returns_401(self, rf: RequestFactory) -> None:
        mw = self._make_middleware()
        request = rf.get("/api/v1/clubs/")
        response = mw(request)
        assert response.status_code == 401
        import json

        assert json.loads(response.content)["detail"]

    def test_malformed_authorization_returns_401(self, rf: RequestFactory) -> None:
        mw = self._make_middleware()
        request = rf.get("/api/v1/clubs/", **_bearer("Token abc"))
        response = mw(request)
        assert response.status_code == 401

    def test_lowercase_bearer_is_accepted(self, rf: RequestFactory, monkeypatch) -> None:
        import auth_clerk.middleware as mw

        called: dict[str, Any] = {}

        def fake_verify(request: Any, token: str) -> RequestState:
            called["token"] = token
            return RequestState(
                status=AuthStatus.SIGNED_IN,
                payload={"sub": "user_xyz"},
                token="x",
            )

        monkeypatch.setattr(mw, "_verify_token", fake_verify)
        middleware = self._make_middleware()
        request = rf.get("/api/v1/clubs/", **_bearer("bearer some.jwt"))
        middleware(request)
        assert called["token"] == "some.jwt"

    def test_signed_in_state_sets_request_user(
        self, rf: RequestFactory, monkeypatch
    ) -> None:
        import auth_clerk.middleware as mw
        from django.contrib.auth import get_user_model

        User = get_user_model()
        state = RequestState(
            status=AuthStatus.SIGNED_IN,
            payload={"sub": "user_alpha", "email": "a@example.com", "name": "Alpha"},
            token="x",
        )
        monkeypatch.setattr(mw, "_verify_token", lambda req, tok: state)
        middleware = self._make_middleware()
        request = rf.get("/api/v1/clubs/", **_bearer("Bearer some.jwt"))
        middleware(request)
        # Auto-provisioned on first sign-in.
        user = User.objects.get(clerk_user_id="user_alpha")
        assert request.user == user
        assert user.username == "Alpha"
        assert user.email == "a@example.com"
        assert user.level == 3.00  # type: ignore[attr-defined]
        assert user.role == User.Role.PLAYER

    def test_signed_out_state_returns_401(
        self, rf: RequestFactory, monkeypatch
    ) -> None:
        import auth_clerk.middleware as mw
        from clerk_backend_api.security.types import AuthErrorReason

        state = RequestState(
            status=AuthStatus.SIGNED_OUT,
            reason=AuthErrorReason.SESSION_TOKEN_MISSING,
        )
        monkeypatch.setattr(mw, "_verify_token", lambda req, tok: state)
        middleware = self._make_middleware()
        request = rf.get("/api/v1/clubs/", **_bearer("Bearer abc"))
        response = middleware(request)
        assert response.status_code == 401

    def test_signed_out_state_without_token_still_returns_401(
        self, rf: RequestFactory
    ) -> None:
        # No token, no Authorization header → 401 with a friendly
        # message.
        middleware = self._make_middleware()
        request = rf.get("/api/v1/clubs/")
        response = middleware(request)
        assert response.status_code == 401

    def test_missing_sub_claim_returns_401(
        self, rf: RequestFactory, monkeypatch
    ) -> None:
        import auth_clerk.middleware as mw

        state = RequestState(
            status=AuthStatus.SIGNED_IN,
            payload={"email": "x@example.com"},  # no sub
            token="x",
        )
        monkeypatch.setattr(mw, "_verify_token", lambda req, tok: state)
        middleware = self._make_middleware()
        request = rf.get("/api/v1/clubs/", **_bearer("Bearer abc"))
        response = middleware(request)
        assert response.status_code == 401

    def test_webhook_path_is_skipped(self, rf: RequestFactory) -> None:
        mw = self._make_middleware()
        # No Authorization header — would normally 401 — but the
        # webhook endpoint must be exempt so Svix can deliver.
        request = rf.post("/api/v1/auth/webhook/clerk/")
        response = mw(request)
        # Skipped → falls through to the stub which returns 200.
        assert response.status_code == 200

    def test_static_path_is_skipped(self, rf: RequestFactory) -> None:
        mw = self._make_middleware()
        request = rf.get("/static/admin/css/base.css")
        response = mw(request)
        assert response.status_code == 200

    def test_health_path_is_skipped(self, rf: RequestFactory) -> None:
        mw = self._make_middleware()
        # We don't expose /_health/ from any URLconf yet, but the
        # middleware short-circuits on the prefix regardless.
        request = rf.get("/_health/")
        response = mw(request)
        assert response.status_code == 200


class TestClerkJWTMiddlewareViaClient:
    """End-to-end via the Django test client."""

    def test_protected_endpoint_returns_401_without_token(self, client) -> None:
        # /api/v1/clubs/ is gated by IsAuthenticated (DRF) and the
        # Clerk middleware. Without a token, ClerkJWTMiddleware should
        # answer 401 before DRF even runs.
        response = client.get("/api/v1/clubs/")
        assert response.status_code == 401

    def test_protected_endpoint_returns_200_with_valid_token(
        self, client, bypass_clerk_auth, make_clerk_state
    ) -> None:
        bypass_clerk_auth(make_clerk_state(sub="user_view_1"))
        response = client.get(
            "/api/v1/clubs/", HTTP_AUTHORIZATION="Bearer test.jwt.token"
        )
        assert response.status_code == 200

    def test_existing_token_reuses_user(
        self, client, bypass_clerk_auth, make_clerk_state, user_factory
    ) -> None:
        from django.contrib.auth import get_user_model

        User = get_user_model()
        existing = user_factory(clerk_user_id="user_view_2")
        bypass_clerk_auth(
            make_clerk_state(
                sub="user_view_2", email=existing.email, name=existing.username
            )
        )
        client.get("/api/v1/clubs/", HTTP_AUTHORIZATION="Bearer test.jwt.token")
        assert User.objects.filter(clerk_user_id="user_view_2").count() == 1
