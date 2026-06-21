"""URL routing for the auth_clerk app.

Mounted at ``/api/v1/auth/`` (see ``padel/urls.py``).
"""
from __future__ import annotations

from django.urls import path

from . import views

app_name = "auth_clerk"

urlpatterns = [
    path("webhook/clerk/", views.clerk_webhook, name="clerk_webhook"),
    path("health/", views.health, name="health"),
]
