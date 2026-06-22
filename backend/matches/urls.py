"""URL routing for the matches app.

Mounted at ``/api/v1/`` (see ``padel/urls.py``).

Routes
------
- ``POST /slots/{slot_id}/match/`` — ``CreateMatchFromSlotView`` (host-first signup).
- ``GET  /matches/{pk}/`` — ``MatchDetailView`` (full match detail).
- ``POST /matches/{pk}/join/`` — ``JoinMatchView`` (self-signup).
- ``POST /matches/{pk}/leave/`` — ``LeaveMatchView``.
- ``POST /matches/{pk}/cancel/`` — ``CancelMatchView`` (admin only).
- ``POST /matches/{pk}/override-add/`` — ``AdminAddPlayerView`` (admin only).

We use explicit ``path()`` entries rather than a router because
the actions live on different URL shapes and don't map cleanly
to a single resource (cancel/override-add are POSTs to the
match itself, but join/leave could equally be ``POST /matches/{id}/players/``
in a future iteration). Keeping the routes explicit makes
endpoint evolution easier.
"""
from __future__ import annotations

from django.urls import path

from . import views

app_name = "matches"

urlpatterns = [
    path(
        "slots/<int:slot_id>/match/",
        views.CreateMatchFromSlotView.as_view(),
        name="create_match_from_slot",
    ),
    path(
        "matches/<int:pk>/",
        views.MatchDetailView.as_view(),
        name="match_detail",
    ),
    path(
        "matches/<int:pk>/join/",
        views.JoinMatchView.as_view(),
        name="join_match",
    ),
    path(
        "matches/<int:pk>/leave/",
        views.LeaveMatchView.as_view(),
        name="leave_match",
    ),
    path(
        "matches/<int:pk>/cancel/",
        views.CancelMatchView.as_view(),
        name="cancel_match",
    ),
    path(
        "matches/<int:pk>/override-add/",
        views.AdminAddPlayerView.as_view(),
        name="admin_add_player",
    ),
]
