"""Idempotency-Key support for mutating endpoints.

Mobile clients with flaky networks can accidentally retry the same
mutation (network timeout followed by user-driven "try again" tap).
The ``Idempotency-Key`` header lets the client signal "this is the
same logical request — return the cached response instead of
re-running it".

Cache strategy
--------------
We cache the response (``status_code`` + ``body``) keyed by
``Idempotency-Key + request.path + user_id``, for
``settings.IDEMPOTENCY_KEY_TTL_SECONDS``. Cached responses are
returned verbatim on retry. The user-id scope prevents one user's
key from masking another user's request.

For MVP this uses Django's ``LocMemCache`` (in-process, per-worker).
Production should swap to ``RedisCache`` for multi-worker safety —
both are configurable through the standard ``CACHES`` setting.

Usage
-----
Inside a view::

    idem_key = request.headers.get(IDEMPOTENCY_HEADER, "")
    if idem_key:
        cached = get_cached(idem_key, request)
        if cached is not None:
            status_code, body = cached
            return Response(body, status=status_code)

    # ... do the work ...

    response = Response(body, status=status_code)
    if idem_key:
        store(idem_key, request, status_code, body)
    return response
"""
from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.cache import cache
from rest_framework.request import Request


IDEMPOTENCY_HEADER = "Idempotency-Key"


def _make_cache_key(key: str, path: str, user_id: int) -> str:
    """Build the namespaced cache key.

    Scoping by user id keeps two different users with the same
    client-generated key from colliding on the same endpoint.
    """
    return f"idempotency:{user_id}:{path}:{key}"


def get_cached(key: str, request: Request) -> tuple[int, Any] | None:
    """Return ``(status_code, body)`` if a cached response exists.

    Returns ``None`` when ``key`` is empty (caller didn't opt into
    idempotency) or no cached response has been stored for this
    key+path+user combination yet.
    """
    if not key:
        return None
    if not request.user or not getattr(request.user, "pk", None):
        # Anonymous request — no scope, no caching.
        return None
    cache_key = _make_cache_key(key, request.path, request.user.pk)
    return cache.get(cache_key)


def store(key: str, request: Request, status_code: int, body: Any) -> None:
    """Cache the response for the idempotency window.

    No-op when ``key`` is empty or the request is anonymous (no
    user scope to key under).
    """
    if not key:
        return
    if not request.user or not getattr(request.user, "pk", None):
        return
    cache_key = _make_cache_key(key, request.path, request.user.pk)
    cache.set(
        cache_key,
        (status_code, body),
        timeout=settings.IDEMPOTENCY_KEY_TTL_SECONDS,
    )