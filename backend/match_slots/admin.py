"""Django admin registrations for the match_slots app."""
from django.contrib import admin

from .models import MatchSlot


@admin.register(MatchSlot)
class MatchSlotAdmin(admin.ModelAdmin):
    list_display = ("court", "start_time", "end_time", "is_active")
    list_filter = ("is_active",)
    raw_id_fields = ("court",)
    date_hierarchy = "start_time"