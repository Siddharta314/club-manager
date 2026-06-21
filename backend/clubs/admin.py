"""Django admin registrations for the clubs app."""
from django.contrib import admin

from .models import Club, Court, Schedule


@admin.register(Club)
class ClubAdmin(admin.ModelAdmin):
    list_display = ("name", "address", "created_by", "created_at")
    search_fields = ("name", "address")
    raw_id_fields = ("created_by",)


@admin.register(Court)
class CourtAdmin(admin.ModelAdmin):
    list_display = ("name", "club", "is_active")
    list_filter = ("is_active",)
    raw_id_fields = ("club",)
    search_fields = ("name",)


@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = ("court", "weekday", "start_time", "end_time", "duration_minutes")
    list_filter = ("weekday",)
    raw_id_fields = ("court",)