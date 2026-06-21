"""Function-based views for the auth_clerk app.

The webhook view lives in ``webhooks.py``; this module exists so the
``urls.py`` import path is consistent.
"""
from __future__ import annotations

from django.http import HttpRequest, JsonResponse

from .webhooks import clerk_webhook

__all__ = ["clerk_webhook"]


def health(_request: HttpRequest) -> JsonResponse:
    """Tiny liveness probe used by docker / k8s / load balancers.

    Kept under auth_clerk because the webhook endpoint is mounted next
    to it under ``/api/v1/auth/`` and avoids creating a separate app.
    """
    return JsonResponse({"status": "ok"})
