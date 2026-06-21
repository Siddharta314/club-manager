"""Players app — minimal placeholder.

PR 1 ships a stub User so Django can resolve `AUTH_USER_MODEL = "players.User"`
in `padel.settings`. PR 5 replaces this with the full custom user model
(Clerk integration, level, club, role, push tokens, notification toggles).
"""
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Placeholder. Replaced in PR 5."""

    class Meta:
        app_label = "players"