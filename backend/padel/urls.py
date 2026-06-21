"""URL configuration for the padel MVP project.

The API surface is mounted under `/api/v1/`. Per-capability URLconfs are wired
in later PRs as those apps gain views.
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # Capability URLconfs are added incrementally per PR.
    # path("api/v1/clubs/", include("clubs.urls")),
    # path("api/v1/", include("auth_clerk.urls")),
]