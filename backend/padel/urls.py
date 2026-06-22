"""URL configuration for the padel MVP project.

The API surface is mounted under ``/api/v1/``. Per-capability URLconfs are
wired in incrementally per PR.
"""
from __future__ import annotations

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.permissions import AllowAny

# Schema endpoints are intentionally public — they're a
# developer-facing surface (Swagger UI / raw schema), not part of
# the authenticated API. We override the global
# ``DEFAULT_PERMISSION_CLASSES = IsAuthenticated`` here.
spectacular_api_view = SpectacularAPIView.as_view(permission_classes=[AllowAny])
spectacular_swagger_view = SpectacularSwaggerView.as_view(
    permission_classes=[AllowAny]
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/auth/", include("auth_clerk.urls")),
    path("api/v1/", include("clubs.urls")),
    # PR 3: matches lifecycle + companions. Both apps share the
    # ``/api/v1/`` prefix because some of their endpoints are
    # cross-cutting (e.g. ``/matches/{id}/companions/`` mixes both
    # apps' resources). Keeping a single include per app keeps the
    # URL files focused and easy to diff.
    path("api/v1/", include("matches.urls")),
    path("api/v1/", include("companions.urls")),
    # PR 4: chat polling endpoint + players /me/ endpoints.
    path("api/v1/", include("chat.urls")),
    path("api/v1/", include("players.urls")),
    # PR 4: OpenAPI schema + Swagger UI for development.
    path("api/schema/", spectacular_api_view, name="schema"),
    path("api/docs/", spectacular_swagger_view, name="swagger-ui"),
]
