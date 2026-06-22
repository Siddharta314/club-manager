"""URL routing for the chat app.

Mounted at ``/api/v1/`` (see ``padel/urls.py``).

Routes
------
- ``GET  /matches/{pk}/messages/`` — list messages (polling endpoint
  with ``?since={last_id}`` cursor).
- ``POST /matches/{pk}/messages/`` — post a message as the request
  user.

A single ``APIView`` handles both verbs so the URL stays identical
for read and write — DRF dispatches on the HTTP method.
"""
from __future__ import annotations

from django.urls import path

from chat.views import ChatMessageListView


app_name = "chat"

urlpatterns = [
    path(
        "matches/<int:pk>/messages/",
        ChatMessageListView.as_view(),
        name="chat_messages",
    ),
]