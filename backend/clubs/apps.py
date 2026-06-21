"""clubs app configuration.

We import the signal module from ``ready()`` so Django wires the
post_save handler as soon as the app registry is populated. The
import is guarded with ``# noqa: F401`` because the module is loaded
purely for its side-effect of registering receivers.
"""
from __future__ import annotations

from django.apps import AppConfig


class ClubsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "clubs"
    verbose_name = "Clubs"

    def ready(self) -> None:
        from . import signals  # noqa: F401 — registers post_save receiver
