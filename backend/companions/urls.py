"""URL routing for the companions app.

Mounted at ``/api/v1/`` (see ``padel/urls.py``).

Routes
------
- ``POST /matches/{pk}/companions/`` — ``RegisterCompanionView``
  (register a companion on a match).
- ``DELETE /companions/{pk}/`` — ``CompanionDetailView`` (remove a
  companion).

The split URL shapes match the spec; the collection POST is
nested under the match, while the item DELETE is by companion id
because once a companion is registered the match reference is
implied.
"""
from __future__ import annotations

from django.urls import path

from . import views

app_name = "companions"

urlpatterns = [
    path(
        "matches/<int:pk>/companions/",
        views.RegisterCompanionView.as_view(),
        name="register_companion",
    ),
    path(
        "companions/<int:pk>/",
        views.CompanionDetailView.as_view(),
        name="companion_detail",
    ),
]
