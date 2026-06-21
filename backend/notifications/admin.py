"""Django admin registrations for the notifications app."""
from django.contrib import admin

from .models import NotificationLog


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ("user", "event_type", "channel", "status", "sent_at", "created_at")
    list_filter = ("event_type", "channel", "status")
    raw_id_fields = ("user",)
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "updated_at")