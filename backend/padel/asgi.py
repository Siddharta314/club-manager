"""ASGI entry point for the padel MVP backend."""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "padel.settings")

application = get_asgi_application()