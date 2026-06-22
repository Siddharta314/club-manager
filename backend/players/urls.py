"""URL routing for the players app.

Mounted at ``/api/v1/`` (see ``padel/urls.py``).

Routes
------
- ``GET/PATCH /me/``              — ``MeView`` (full profile + partial
  update).
- ``PATCH       /me/push-token/`` — ``PushTokenView`` (Expo token
  registration).
- ``PATCH       /me/notifications/`` — ``NotificationPreferencesView``
  (opt-in toggles).

A single ``APIView`` handles GET and PATCH on ``/me/`` because
the URL is identical; DRF dispatches on the HTTP method.
"""
from __future__ import annotations

from django.urls import path

from players.views import MeView, NotificationPreferencesView, PushTokenView


app_name = "players"

urlpatterns = [
    path("me/", MeView.as_view(), name="me"),
    path("me/push-token/", PushTokenView.as_view(), name="me_push_token"),
    path(
        "me/notifications/",
        NotificationPreferencesView.as_view(),
        name="me_notifications",
    ),
]