"""auth_clerk app — Clerk authentication integration.

This module owns three concerns:

1. **JWT middleware** (``middleware.py``) — verifies ``Authorization:
   Bearer <jwt>`` on every request using Clerk's ``authenticate_request``
   helper, caches JWKS for 1h, sets ``request.user`` to the corresponding
   Django ``User``.

2. **Webhooks** (``webhooks.py``) — receives ``user.created``,
   ``user.updated``, and ``user.deleted`` events from Clerk's Svix-signed
   endpoint and keeps the Django ``User`` mirror in sync.

3. **Bootstrap command** (``management/commands/promote_superadmin.py``) —
   promotes a Clerk user to ``role=super_admin`` with Django admin access.

Tests use mocks for Clerk's ``authenticate_request`` and Svix's
``Webhook.verify``; no real network calls.
"""
from __future__ import annotations

default_app_config = "auth_clerk.apps.AuthClerkConfig"
