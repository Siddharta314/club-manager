"""URL routing for the clubs app.

Mounted at ``/api/v1/`` (see ``padel/urls.py``).

Routes
------
- ``/clubs/`` and ``/clubs/{pk}/`` — ``ClubViewSet`` (list/retrieve/create/
  update/destroy).
- ``/clubs/{club_pk}/courts/`` and ``/clubs/{club_pk}/courts/{pk}/`` —
  ``CourtViewSet`` nested under club.
- ``/clubs/{club_pk}/courts/{court_pk}/schedule/`` and
  ``/clubs/{club_pk}/courts/{court_pk}/schedule/{pk}/`` —
  ``ScheduleViewSet`` nested under court.
- ``/clubs/{pk}/slots/`` — ``ClubSlotListView`` (read-only slot listing).
"""
from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "clubs"

router = DefaultRouter()
router.register(r"clubs", views.ClubViewSet, basename="club")

# Nested resources. We wire them as explicit paths because the project
# doesn't depend on drf-nested-routers yet (the prompt's commit
# sequence stays within stdlib DRF). Adding the dep is a future PR if
# nesting depth grows.
club_list = views.ClubViewSet.as_view({"get": "list", "post": "create"})
club_detail = views.ClubViewSet.as_view(
    {
        "get": "retrieve",
        "put": "update",
        "patch": "partial_update",
        "delete": "destroy",
    }
)
club_courts = views.CourtViewSet.as_view({"get": "list", "post": "create"})
club_court_detail = views.CourtViewSet.as_view(
    {
        "get": "retrieve",
        "put": "update",
        "patch": "partial_update",
        "delete": "destroy",
    }
)
court_schedule = views.ScheduleViewSet.as_view({"get": "list", "post": "create"})
court_schedule_detail = views.ScheduleViewSet.as_view(
    {
        "get": "retrieve",
        "put": "update",
        "patch": "partial_update",
        "delete": "destroy",
    }
)


urlpatterns = [
    # Club CRUD
    path("clubs/", club_list, name="club-list"),
    path("clubs/<int:pk>/", club_detail, name="club-detail"),
    # Nested courts
    path(
        "clubs/<int:club_pk>/courts/",
        club_courts,
        name="club-courts-list",
    ),
    path(
        "clubs/<int:club_pk>/courts/<int:pk>/",
        club_court_detail,
        name="club-courts-detail",
    ),
    # Nested schedule
    path(
        "clubs/<int:club_pk>/courts/<int:court_pk>/schedule/",
        court_schedule,
        name="court-schedule-list",
    ),
    path(
        "clubs/<int:club_pk>/courts/<int:court_pk>/schedule/<int:pk>/",
        court_schedule_detail,
        name="court-schedule-detail",
    ),
    # Slot listing
    path(
        "clubs/<int:pk>/slots/",
        views.ClubSlotListView.as_view(),
        name="club-slots",
    ),
]
