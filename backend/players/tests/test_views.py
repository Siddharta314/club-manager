"""Tests for /api/v1/me/ endpoint (REQ-ADMIN-001, REQ-ADMIN-002).

Mirrors the bypass_clerk_auth + make_clerk_state pattern from
``backend/clubs/tests/test_views.py:18-59``: each authenticated test
patches ``auth_clerk.middleware._verify_token`` to return a
``SIGNED_IN`` ``RequestState`` whose ``sub`` claim resolves to the
Django user created in ``setUp``.
"""
from __future__ import annotations

from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from auth_clerk import middleware as clerk_mw
from clerk_backend_api.security.types import AuthStatus, RequestState
from clubs.models import Club
from players.models import User


class TestMeEndpoint(TestCase):
    """Tests for ``GET /api/v1/me/`` + ``PATCH`` endpoints (REQ-ADMIN-002)."""

    # Stable Clerk user identifier — used both when creating the Django
    # user and when forging the ``sub`` claim in the bypassed middleware.
    USER_CLERK_ID = "user_ana_test"

    def setUp(self) -> None:
        # ``created_by`` is a NOT NULL FK on Club — declare the user first
        # so the FK resolves, then create the club, then attach it back.
        self.user = User.objects.create_user(
            username=self.USER_CLERK_ID,
            email="ana@test.com",
            clerk_user_id=self.USER_CLERK_ID,
            first_name="Ana",
            last_name="García",
            level=3.5,
            role="player",
        )
        self.club = Club.objects.create(
            name="Test Club",
            address="123 Test St",
            created_by=self.user,
        )
        self.user.club = self.club
        self.user.save(update_fields=["club"])
        # Forge a SIGNED_IN RequestState that the patched middleware
        # will hand back, so the request resolves to ``self.user``.
        state = RequestState(
            status=AuthStatus.SIGNED_IN,
            reason=None,
            token="mock.jwt.token",
            payload={
                "sub": self.USER_CLERK_ID,
                "email": "ana@test.com",
                "name": "Ana García",
            },
        )
        patcher = mock.patch.object(
            clerk_mw, "_verify_token", return_value=state
        )
        self._auth_patch = patcher.start()
        self.addCleanup(patcher.stop)

        # Use DRF's APIClient (NOT django.test.Client) so ``format='json'``
        # works on PATCH calls — and set the bearer token the Clerk
        # middleware looks for.
        self.client = APIClient()
        self.client.defaults["HTTP_AUTHORIZATION"] = "Bearer mock.jwt.token"

    # ----------------------------------------------------------------- (a)
    def test_unauthenticated_get_me_returns_401(self) -> None:
        """No Authorization header → 401 (REQ-ADMIN-002 a)."""
        anon = APIClient()
        response = anon.get("/api/v1/me/")
        self.assertEqual(response.status_code, 401)

    # ----------------------------------------------------------------- (b)
    def test_get_me_returns_user_profile(self) -> None:
        """Authed GET /me/ → 200; body has profile fields, NO ``photo`` (b).

        RED at commit time: ``MeSerializer.Meta.fields`` declares
        ``"photo"`` but ``User`` has no ``photo`` column, so DRF's
        introspection raises ``FieldDoesNotExist`` and the view 500s.
        Captured in the apply report.
        """
        response = self.client.get("/api/v1/me/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        # REQ-ADMIN-001: photo MUST NOT be in the response shape.
        self.assertNotIn("photo", body)
        # REQ-ADMIN-002 (b): required keys are present and correct.
        self.assertEqual(body["email"], "ana@test.com")
        self.assertEqual(body["first_name"], "Ana")
        self.assertEqual(body["last_name"], "García")
        # ``LevelField`` is a DecimalField — DRF serializes Decimals as
        # strings to preserve precision (``"3.50"`` not ``3.5``). The
        # Mobile type expects a number and parses on its end; this is
        # the pre-existing serialization contract — out of scope here.
        self.assertEqual(body["level"], "3.50")
        self.assertEqual(body["club"], self.club.id)
        self.assertEqual(body["role"], "player")
        self.assertIn("notify_push", body)
        self.assertIn("notify_email", body)

    # ----------------------------------------------------------------- (c)
    def test_patch_me_updates_notify_push_and_notify_email(self) -> None:
        """PATCH /me/ with new flag values → 200, persisted (REQ-ADMIN-002 c)."""
        response = self.client.patch(
            "/api/v1/me/",
            {"notify_push": False, "notify_email": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.notify_push)
        self.assertTrue(self.user.notify_email)

    # ----------------------------------------------------------------- (d)
    def test_patch_me_push_token_returns_204(self) -> None:
        """PATCH /me/push-token/ → 204, push_token persisted (REQ-ADMIN-002 d).

        ``PushTokenView`` is PATCH only (not POST). Asserts 204, not 200.
        """
        response = self.client.patch(
            "/api/v1/me/push-token/",
            {"push_token": "abc"},
            format="json",
        )
        self.assertEqual(response.status_code, 204)
        self.user.refresh_from_db()
        self.assertEqual(self.user.push_token, "abc")

    # ----------------------------------------------------------------- extra
    def test_patch_me_notifications_returns_200(self) -> None:
        """PATCH /me/notifications/ with new flags → 200, persisted.

        The dedicated notifications endpoint (``NotificationPreferencesView``)
        accepts partial updates of the two opt-in flags.
        """
        response = self.client.patch(
            "/api/v1/me/notifications/",
            {"notify_push": False, "notify_email": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["notify_push"], False)
        self.assertEqual(body["notify_email"], True)
        self.user.refresh_from_db()
        self.assertFalse(self.user.notify_push)
        self.assertTrue(self.user.notify_email)

    def test_patch_me_notifications_only_updates_provided_fields(self) -> None:
        """PATCH /me/notifications/ with one field doesn't reset the other.

        Partial-update semantics — sending only ``notify_push`` must leave
        ``notify_email`` untouched.
        """
        self.user.notify_push = True
        self.user.notify_email = False
        self.user.save()
        response = self.client.patch(
            "/api/v1/me/notifications/",
            {"notify_push": False},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.notify_push)  # updated
        self.assertFalse(self.user.notify_email)  # unchanged

    def test_patch_me_push_token_with_empty_value_returns_204_and_clears(self) -> None:
        """PATCH /me/push-token/ with empty string → 204 and clears the token.

        Empty string clears the Expo Push token. With
        ``allow_blank=True``, an empty PATCH sets ``push_token`` to ``""``
        so the notifications pipeline (``if user.push_token:``) treats the
        user as having no push token. Aligns with the model default
        (``CharField(blank=True, default="")``) and with the model-level
        contract that an empty string is a valid "no token" state.
        """
        self.user.push_token = "existing"
        self.user.save()
        response = self.client.patch(
            "/api/v1/me/push-token/",
            {"push_token": ""},
            format="json",
        )
        self.assertEqual(response.status_code, 204)
        self.user.refresh_from_db()
        # Token is cleared — serializer allows blank and the empty
        # payload is persisted as "".
        self.assertEqual(self.user.push_token, "")

    def test_patch_me_push_token_with_non_empty_value_still_returns_204(self) -> None:
        """Non-empty push_token PATCH → 204 and persists the value (positive case).

        Triangulation: documents the existing positive contract explicitly
        so the contract is covered in BOTH directions — empty clears,
        non-empty sets. Without this test, a future regression that
        flips back to ``allow_blank=False`` (or a stricter ``allow_null``
        setting) would only be caught by the empty-string case; this
        test guards the happy path alongside it.
        """
        response = self.client.patch(
            "/api/v1/me/push-token/",
            {"push_token": "ExponentPushToken[abc]"},
            format="json",
        )
        self.assertEqual(response.status_code, 204)
        self.user.refresh_from_db()
        self.assertEqual(self.user.push_token, "ExponentPushToken[abc]")
