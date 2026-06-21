"""Django admin registrations for the companions app."""
from django.contrib import admin

from .models import Companion


@admin.register(Companion)
class CompanionAdmin(admin.ModelAdmin):
    list_display = ("name", "level", "match", "sponsored_by", "created_at")
    search_fields = ("name",)
    raw_id_fields = ("match", "sponsored_by")