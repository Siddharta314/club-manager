"""Django settings for the padel MVP backend.

Environment-driven via django-environ; see `.env.example` for the full set of
variables. Defaults are intentionally conservative so that the project boots in
development without a `.env` file present.
"""
from __future__ import annotations

from pathlib import Path

import environ

# ---------------------------------------------------------------------------
# Paths & environment
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CORS_ALLOWED_ORIGINS=(list, ["http://localhost:8081"]),
    TIME_ZONE=(str, "Europe/Madrid"),
    CLERK_JWT_AUDIENCE=(list, []),
)

# Read .env if present; never required.
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env(
    "SECRET_KEY",
    default="dev-insecure-secret-key-do-not-use-in-production",
)
DEBUG = env.bool("DEBUG")

# ---------------------------------------------------------------------------
# Core Django
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    # Django core
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "corsheaders",
    "unfold",
    "django_q",
    # Local apps (one per capability)
    "clubs.apps.ClubsConfig",
    "match_slots.apps.MatchSlotsConfig",
    "matches.apps.MatchesConfig",
    "companions.apps.CompanionsConfig",
    "players.apps.PlayersConfig",
    "chat.apps.ChatConfig",
    "notifications.apps.NotificationsConfig",
    "auth_clerk.apps.AuthClerkConfig",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # PR 2: Clerk JWT verification. Must come AFTER AuthenticationMiddleware
    # so DRF's `request.user` resolution stays consistent.
    "auth_clerk.middleware.ClerkJWTMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "padel.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "padel.wsgi.application"
ASGI_APPLICATION = "padel.asgi.application"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# Default matches the docker-compose Postgres service (padel:padel@db/padel).
# For local non-docker dev override DATABASE_URL via .env to point at
# postgresql://padel:padel@localhost:5433/padel. We use host port 5433
# (instead of the Postgres default 5432) to avoid colliding with any
# local Postgres install a developer may already be running.
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgresql://padel:padel@localhost:5433/padel",
    ),
}

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "players.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE")
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static / media
# ---------------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = env("MEDIA_URL", default="/media/")
MEDIA_ROOT = env("MEDIA_ROOT", default=str(BASE_DIR / "media"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Hosts / CORS
# ---------------------------------------------------------------------------
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = True

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
# PR 2: ClerkJWTMiddleware sets `request.user` on the Django request
# before DRF runs. We add `ClerkSessionAuthentication` (in
# `auth_clerk.authentication`) as the DRF auth class so DRF's wrapped
# `Request.user` picks up the same user without re-running JWT
# verification.
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "auth_clerk.authentication.ClerkSessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}

# ---------------------------------------------------------------------------
# django-unfold (admin theme)
# ---------------------------------------------------------------------------
UNFOLD = {
    "SITE_TITLE": "Padel MVP Admin",
    "SITE_HEADER": "Padel MVP",
    "SITE_URL": "/",
    "DASHBOARD_CALLBACK": "django_q.dashboard.views.dashboard",
    "COLORS": {
        "primary": {
            "50": "#f0f9ff",
            "100": "#e0f2fe",
            "200": "#bae6fd",
            "300": "#7dd3fc",
            "400": "#38bdf8",
            "500": "#0ea5e9",
            "600": "#0284c7",
            "700": "#0369a1",
            "800": "#075985",
            "900": "#0c4a6e",
            "950": "#082f49",
        },
    },
}

# ---------------------------------------------------------------------------
# Django Q2 (async task broker)
# ---------------------------------------------------------------------------
# ORM broker for development (zero infra). Swap to Redis for production by
# overriding `Q_CLUSTER` via environment.
Q_CLUSTER = {
    "name": "padel",
    "workers": 4,
    "timeout": 60,
    "retry": 120,
    "queue_limit": 50,
    "bulk": 10,
    "poll": 0.5,
    "orm": "default",  # use the Django ORM as the broker
}

# ---------------------------------------------------------------------------
# Clerk (PR 2)
# ---------------------------------------------------------------------------
CLERK_SECRET_KEY = env("CLERK_SECRET_KEY", default="")
CLERK_PUBLISHABLE_KEY = env("CLERK_PUBLISHABLE_KEY", default="")
# Optional symmetric secret for offline JWT verification (skips JWKS fetch).
CLERK_JWT_KEY = env("CLERK_JWT_KEY", default="")
CLERK_JWKS_URL = env("CLERK_JWKS_URL", default="")
CLERK_WEBHOOK_SECRET = env("CLERK_WEBHOOK_SECRET", default="")
CLERK_JWT_AUDIENCE = env("CLERK_JWT_AUDIENCE")

# ---------------------------------------------------------------------------
# Third-party integrations (consumed in PR 4)
# ---------------------------------------------------------------------------
RESEND_API_KEY = env("RESEND_API_KEY", default="")
EXPO_ACCESS_TOKEN = env("EXPO_ACCESS_TOKEN", default="")

# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------
MVP_ENABLED = env.bool("MVP_ENABLED", default=True)
