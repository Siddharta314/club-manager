"""WSGI entry point for the padel MVP backend."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "padel.settings")

application = get_wsgi_application()