"""Player ``/me/`` endpoints.

Endpoints
---------
- ``GET   /api/v1/me/``                 — full profile of the request user.
- ``PATCH /api/v1/me/``                 — update profile (name, level, photo,
                                         notification preferences).
- ``PATCH /api/v1/me/push-token/``      — register the Expo push token.
- ``PATCH /api/v1/me/notifications/``   — toggle ``notify_push`` /
                                         ``notify_email``.

Permissions: all endpoints are ``IsAuthenticated`` — the global
DRF default already enforces this; we set it explicitly for
clarity and so future ``permission_classes`` overrides don't
accidentally open these up.

Notes on level self-reporting
-----------------------------
Per the spec, players can self-report their level. Club admins
also edit levels through the same endpoint (admin override is
a future admin UI, not a separate endpoint).
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from players.models import User
from players.serializers import (
    MeSerializer,
    NotificationPreferencesSerializer,
    PushTokenSerializer,
)


class MeView(APIView):
    """``GET /api/v1/me/`` + ``PATCH /api/v1/me/``.

    GET returns the full profile (id, email, name, level, club,
    role, photo, notification flags). PATCH accepts a partial
    update — the mobile client can send just ``level`` after a
    match, or just ``photo`` after editing their avatar.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(MeSerializer(request.user).data, status=status.HTTP_200_OK)

    def patch(self, request: Request) -> Response:
        serializer = MeSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        # No special-case for level edits: the player's self-report
        # path goes through the same serializer that a club admin
        # would use (admin override is a UI concern, not a separate
        # serializer). The serializer's read-only fields (id, email,
        # club, role) stay untouched regardless of body.
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)


class PushTokenView(APIView):
    """``PATCH /api/v1/me/push-token/``.

    Stores the Expo push token on the user so the Q2 worker
    can find it when dispatching a push notification. We save
    just this column (``update_fields``) to avoid touching
    unrelated fields and triggering a spurious updated_at write.
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request: Request) -> Response:
        serializer = PushTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request.user.push_token = serializer.validated_data["push_token"]
        request.user.save(update_fields=["push_token"])
        # 204 No Content: the token was stored; nothing useful to
        # return in the body.
        return Response(status=status.HTTP_204_NO_CONTENT)


class NotificationPreferencesView(APIView):
    """``PATCH /api/v1/me/notifications/``.

    Updates only the two opt-in flags. The response returns the
    new values so the mobile client can sync its toggle UI.
    """

    permission_classes = [IsAuthenticated]

    def patch(self, request: Request) -> Response:
        serializer = NotificationPreferencesSerializer(
            request.user, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)