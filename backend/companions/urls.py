"""URL routing for the companions app.

Mounted at ``/api/v1/`` (see ``padel/urls.py``).

Routes
------
- ``POST   /matches/{pk}/companions/`` — ``RegisterCompanionView``
  (register a companion on a match).
- ``PATCH  /companions/{pk}/`` — ``CompanionDetailView`` (edit
  companion ``name`` and/or ``level``).
- ``DELETE /companions/{pk}/`` — ``CompanionDetailView`` (remove a
  companion).

The split URL shapes match the spec; the collection POST is
nested under the match, while the item PATCH / DELETE are by
companion id because once a companion is registered the match
reference is implied. The same ``CompanionDetailView`` handles
both PATCH and DELETE — DRF's ``APIView`` dispatches on the
HTTP method.
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
