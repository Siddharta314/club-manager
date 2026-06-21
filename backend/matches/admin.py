"""Django admin registrations for the matches app."""
from django.contrib import admin

from .models import Match, MatchPlayer


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ("host", "level_min", "level_max", "is_cancelled")
    list_filter = ("is_cancelled",)
    raw_id_fields = ("host",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(MatchPlayer)
class MatchPlayerAdmin(admin.ModelAdmin):
    list_display = ("match", "user", "joined_at")
    raw_id_fields = ("match", "user")