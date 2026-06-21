"""Django admin registrations for the chat app."""
from django.contrib import admin

from .models import ChatMessage


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("match", "short_text", "author_user", "author_companion", "created_at")
    raw_id_fields = ("match", "author_user", "author_companion")
    date_hierarchy = "created_at"

    @admin.display(description="Text")
    def short_text(self, obj):
        return obj.text[:60]