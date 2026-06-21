"""Clerk JWT verification middleware.

Verifies the ``Authorization: Bearer <jwt>`` header on every request
using ``clerk_backend_api.authenticate_request``. JWKS fetching and
caching are delegated to the Clerk SDK — this module only owns the
process-wide ``Clerk`` client singleton so the underlying httpx
connection pool is reused across requests within the same worker.

Behaviour
---------
- **Skipped paths** (no auth required): webhook endpoint, Django admin,
  static / media URLs, health probe. The middleware returns the request
  unchanged for these so DRF can still serve them.
- **Header missing or malformed** → 401 ``Unauthorized`` JSON response.
- **Token verification fails** → 401 ``Unauthorized`` JSON response.
- **Token valid** → resolve the Clerk ``sub`` claim to a Django ``User``
  (creating it on first sight so sign-in auto-provisions an account),
  set ``request.user`` and ``request.auth``, and let the request through.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from clerk_backend_api import Clerk
from clerk_backend_api.security.types import (
    AuthenticateRequestOptions,
    AuthStatus,
    RequestState,
)
from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse

from .services import get_or_create_user_from_clerk

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Clerk SDK client (singleton)
# ---------------------------------------------------------------------------
# The Clerk SDK fetches JWKS lazily and caches them in-process. Wrapping
# the ``Clerk`` instance in a module-level singleton lets us share the
# underlying httpx connection pool across requests in the same worker.
# Key rotation, TTL, and cache invalidation are entirely owned by the
# SDK — this module does not need its own TTL bookkeeping.
_clerk_client: Clerk | None = None
_clerk_client_lock = threading.Lock()


def _get_clerk_client() -> Clerk:
    """Return the process-wide Clerk SDK client (lazy + thread-safe)."""
    global _clerk_client
    if _clerk_client is None:
        with _clerk_client_lock:
            if _clerk_client is None:
                _clerk_client = Clerk(bearer_auth=settings.CLERK_SECRET_KEY or None)
    return _clerk_client


def _reset_clerk_client_for_tests() -> None:
    """Test hook to drop the cached Clerk client (e.g. after changing
    settings.CLERK_SECRET_KEY in a test)."""
    global _clerk_client
    with _clerk_client_lock:
        _clerk_client = None


# ---------------------------------------------------------------------------
# Path matching
# ---------------------------------------------------------------------------
SKIP_PATH_PREFIXES: tuple[str, ...] = (
    "/api/v1/auth/webhook/",
    "/admin/",
    "/static/",
    "/media/",
    "/_health/",
)


def _should_skip(path: str) -> bool:
    """Return True if the middleware should pass the request through
    without authentication.

    Static and media prefixes are checked via Django's settings rather
    than hard-coded to support future STATIC_URL changes.
    """
    static_url = getattr(settings, "STATIC_URL", "/static/")
    media_url = getattr(settings, "MEDIA_URL", "/media/")
    candidates = (*SKIP_PATH_PREFIXES, static_url, media_url)
    return any(path.startswith(prefix) for prefix in candidates)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
class ClerkJWTMiddleware:
    """Authenticate every request via Clerk JWT.

    Place this AFTER ``AuthenticationMiddleware`` so DRF sees both
    ``request.user`` and the session-aware fallback.
    """

    def __init__(self, get_response: Any) -> None:
        self.get_response = get_response
        # Initialise the singleton at import time when possible so the
        # first request doesn't pay the SDK boot cost. We swallow errors
        # because settings.CLERK_SECRET_KEY may be unset in tests.
        try:
            _get_clerk_client()
        except Exception:  # noqa: BLE001 — defensive, see docstring.
            logger.debug("Clerk client init deferred", exc_info=True)

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if _should_skip(request.path):
            return self.get_response(request)

        token = _extract_bearer_token(request)
        if token is None:
            return _unauthorized("Missing or malformed Authorization header")

        state = _verify_token(request, token)
        if state.status != AuthStatus.SIGNED_IN or state.payload is None:
            reason = state.reason.value[1] if state.reason is not None else "Invalid token"
            logger.info("Clerk auth rejected: %s", reason)
            return _unauthorized(reason)

        clerk_user_id = state.payload.get("sub")
        if not clerk_user_id:
            return _unauthorized("Token missing 'sub' claim")

        user, _ = get_or_create_user_from_clerk(
            clerk_user_id=clerk_user_id,
            email=str(state.payload.get("email") or ""),
            name=_extract_name_from_payload(state.payload),
        )
        # Django's AuthenticationMiddleware uses SimpleLazyObject for
        # ``request.user`` which re-resolves on every attribute access
        # when not previously set. Setting ``request.user`` here would
        # be overwritten by the lazy resolver. Force the underlying
        # ``_user`` attribute and also assign ``request.user`` so DRF's
        # ``Request.user`` property (which delegates to
        # ``_request.user``) picks it up.
        _assign_user(request, user)
        request.auth = state  # type: ignore[attr-defined]
        return self.get_response(request)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _extract_bearer_token(request: HttpRequest) -> str | None:
    """Pull ``<token>`` from a ``Bearer <token>`` header.

    Accepts the literal strings ``Bearer`` and ``bearer`` (Clerk's docs
    mention both depending on the SDK version). Returns ``None`` if the
    header is absent, not a string, or doesn't follow the schema.
    """
    raw = request.META.get("HTTP_AUTHORIZATION", "")
    if not raw:
        return None
    parts = raw.split(None, 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None


def _verify_token(request: HttpRequest, token: str) -> RequestState:
    """Call Clerk's ``authenticate_request`` with the configured options.

    ``jwt_key`` is preferred when supplied (networkless verification);
    otherwise Clerk falls back to the JWKS endpoint, which the SDK
    caches internally.
    """
    options = AuthenticateRequestOptions(
        secret_key=settings.CLERK_SECRET_KEY or None,
        jwt_key=settings.CLERK_JWT_KEY or None,
        audience=settings.CLERK_JWT_AUDIENCE or None,
    )
    return _get_clerk_client().authenticate_request(request, options)


def _extract_name_from_payload(payload: dict[str, Any]) -> str:
    """Pull a human-readable name from a Clerk JWT payload.

    The exact key shape depends on the Clerk session-token template;
    we accept the most common variants so webhook + middleware agree.
    """
    return str(
        payload.get("name")
        or payload.get("username")
        or payload.get("email")
        or ""
    )


def _unauthorized(detail: str) -> JsonResponse:
    """Build the standard 401 JSON response.

    DRF views will also produce 401s, but the middleware must produce
    one without going through DRF (e.g. for paths that aren't views).
    """
    return JsonResponse({"detail": detail}, status=401)


def _assign_user(request: HttpRequest, user: Any) -> None:
    """Replace ``request.user`` with ``user`` for downstream consumers.

    Django's ``AuthenticationMiddleware`` sets ``request.user`` to a
    ``SimpleLazyObject``. Setting ``request.user = my_user`` on a
    not-yet-resolved lazy object would trigger ``_setup()`` (which
    resolves to ``AnonymousUser`` when no session is present) and then
    set ``user`` as an attribute on that ``AnonymousUser`` — discarded
    on the next access.

    DRF adds another layer: ``rest_framework.request.Request`` has its
    own ``user`` property that calls ``_authenticate()`` on first
    access. With no DRF authentication classes configured, that
    resolves to ``AnonymousUser`` even if the Django request carries
    our user.

    To make both layers see ``user`` we:

    1. Replace the lazy object's ``_wrapped`` slot (so the Django
       request resolves to our user).
    2. Set ``request._user`` (DRF's storage slot on the underlying
       Django request — read by ``auth_clerk.authentication.ClerkSessionAuthentication``).
    3. Assign ``request.user`` as a fallback for plain Django requests.
    """
    lazy = request.__dict__.get("user")
    if lazy is not None and hasattr(lazy, "_wrapped"):
        try:
            lazy._wrapped = user
        except (AttributeError, TypeError):
            pass
    # DRF's authentication class reads request._user to populate the
    # wrapped Request.user; without this DRF falls back to AnonymousUser.
    try:
        request._user = user
    except (AttributeError, TypeError):
        pass
    request.user = user
