"""Django admin registrations for the players app."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class UserAdminConfig(UserAdmin):
    """Custom admin for the Clerk-backed User model.

    Adds the padel-specific fields to the user change form and groups the
    notification toggles in their own fieldset. The `club` FK is added in
    the clubs PR and gets folded into the fieldset then.
    """

    list_display = ("username", "email", "role", "level", "is_active")
    list_filter = ("role", "is_active", "notify_push", "notify_email")
    search_fields = ("username", "email", "clerk_user_id")
    ordering = ("username",)

    fieldsets = UserAdmin.fieldsets + (
        (
            "Padel profile",
            {
                "fields": (
                    "clerk_user_id",
                    "level",
                    "role",
                    "push_token",
                    "notify_push",
                    "notify_email",
                ),
            },
        ),
    )