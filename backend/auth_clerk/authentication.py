"""DRF authentication classes for the auth_clerk app.

``ClerkSessionAuthentication`` is the bridge between
``ClerkJWTMiddleware`` and DRF. The middleware sets ``request.user``
on the Django request before DRF runs; this class surfaces that user
to DRF's wrapped ``Request.user`` property.

Why this is needed
------------------
DRF's default ``Request.user`` calls ``_authenticate()`` on first
access. With ``DEFAULT_AUTHENTICATION_CLASSES = []`` (we don't want
DRF to redo JWT verification — the middleware already did it),
``_authenticate`` finds no authenticator and falls back to
``AnonymousUser``. The class below short-circuits that by returning
``request._user`` (set by the middleware) so DRF views see the same
user the middleware authenticated.
"""
from __future__ import annotations

from typing import Any

from rest_framework import authentication
from rest_framework.request import Request


class ClerkSessionAuthentication(authentication.BaseAuthentication):
    """Surface the Clerk-authenticated user to DRF.

    The ``authenticate`` method is required by DRF's base class but
    we never need to re-verify the JWT here — the middleware already
    did. Returning ``None`` tells DRF "no extra auth tuple needed";
    the actual user resolution happens in ``authenticate_credentials``
    which we override to read ``request._user``.

    This means DRF views see ``request.user`` set to the Django user
    the middleware authenticated, without ever hitting the Clerk SDK
    a second time.
    """

    def authenticate(self, request: Request) -> tuple[Any, Any] | None:
        # The middleware sets ``request._request._user`` (= the
        # underlying Django request's ``_user`` attribute). DRF reads
        # ``request._user`` on its wrapped Request. We return a tuple
        # of ``(user, auth)`` so DRF populates its own ``_user`` slot.
        django_request = request._request  # type: ignore[attr-defined]
        user = getattr(django_request, "_user", None)
        if user is None:
            # Fallback to the lazy resolver — AuthenticationMiddleware
            # may have set this.
            user = getattr(django_request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return None
        auth = getattr(django_request, "auth", None)
        return (user, auth)
