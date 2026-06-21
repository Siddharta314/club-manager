"""promote_superadmin — bootstrap the first Django admin from a Clerk user ID.

Usage:
    python manage.py promote_superadmin user_2abc...

Sets ``role='super_admin'`` and the Django admin flags
(``is_staff=True``, ``is_superuser=True``) on the matching User.
Creates the User if it doesn't exist yet (handy when bootstrapping
right after Clerk is wired up but before the first ``user.created``
event has been processed).

Idempotent: re-running the command against an already-promoted user
is a no-op (apart from a log line) so it can be used in deployment
scripts without conditional logic.
"""
from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from auth_clerk.services import get_or_create_user_from_clerk

User = get_user_model()


class Command(BaseCommand):
    """Promote a Clerk user to super_admin (idempotent)."""

    help = (
        "Promote a Clerk user to super_admin (sets role='super_admin', "
        "is_staff=True, is_superuser=True). Creates the Django user if it "
        "doesn't exist yet."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "clerk_user_id",
            type=str,
            help="The Clerk user ID (the JWT 'sub' claim) to promote.",
        )
        parser.add_argument(
            "--email",
            type=str,
            default="",
            help="Optional fallback email when creating the user on the fly.",
        )
        parser.add_argument(
            "--name",
            type=str,
            default="",
            help="Optional fallback username when creating the user on the fly.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        clerk_user_id: str = options["clerk_user_id"]
        email: str = options.get("email", "") or ""
        name: str = options.get("name", "") or ""

        if not clerk_user_id:
            raise CommandError("clerk_user_id is required")

        user, created = get_or_create_user_from_clerk(
            clerk_user_id=clerk_user_id,
            email=email,
            name=name or clerk_user_id,
        )

        updated_fields: list[str] = []
        if user.role != User.Role.SUPER_ADMIN:
            user.role = User.Role.SUPER_ADMIN
            updated_fields.append("role")
        if not user.is_staff:
            user.is_staff = True
            updated_fields.append("is_staff")
        if not user.is_superuser:
            user.is_superuser = True
            updated_fields.append("is_superuser")

        if updated_fields:
            user.save(update_fields=updated_fields)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Promoted clerk_id={clerk_user_id} "
                    f"(created={created}, fields={updated_fields})"
                )
            )
        else:
            self.stdout.write(
                f"User clerk_id={clerk_user_id} already a super_admin (no changes)"
            )
