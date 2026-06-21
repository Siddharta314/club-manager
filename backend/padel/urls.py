"""URL configuration for the padel MVP project.

The API surface is mounted under `/api/v1/`. Per-capability URLconfs are wired
in incrementally per PR.
"""
from __future__ import annotations

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/auth/", include("auth_clerk.urls")),
    # clubs/ URLs land in PR 2 commit 9 (after viewsets exist).
]
