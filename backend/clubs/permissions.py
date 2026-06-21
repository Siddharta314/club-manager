"""DRF permissions for the clubs app.

Permission helpers are kept tiny and composable — they assume
``request.user`` is already populated by ClerkJWTMiddleware. If that
middleware isn't installed, ``request.user`` will be ``AnonymousUser``
and these permissions will deny access.
"""
from __future__ import annotations

from rest_framework import permissions
from rest_framework.request import Request
from rest_framework.views import APIView

from .models import Club


def _is_authenticated(request: Request) -> bool:
    """Helper to keep the ``request.user.is_authenticated`` check uniform."""
    user = getattr(request, "user", None)
    return bool(user and user.is_authenticated)


class IsAuthenticatedReadOnly(permissions.BasePermission):
    """Read access for any authenticated user; write requires explicit
    ownership below.

    Used on the ClubViewSet ``list``/``retrieve`` actions so anonymous
    users get 401 (we don't expose the club directory publicly).
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        return _is_authenticated(request) or request.method in permissions.SAFE_METHODS


class IsClubAdmin(permissions.BasePermission):
    """Object-level: the request user is the admin of the object's club.

    Looks at ``obj.club`` when present (Court, Schedule, MatchSlot). For
    Club objects, it checks ``obj.created_by``. Super_admin short-circuits
    so platform staff can edit anything.
    """

    message = "Only the club admin can modify this object."

    def has_permission(self, request: Request, view: APIView) -> bool:
        # Must be authenticated for any write — reads are governed at
        # the view layer (IsAuthenticatedReadOnly).
        if request.method in permissions.SAFE_METHODS:
            return _is_authenticated(request)
        return _is_authenticated(request)

    def has_object_permission(self, request: Request, view: APIView, obj: Club) -> bool:
        user = request.user
        if not _is_authenticated(request):
            return False
        if user.is_super_admin:
            return True
        # Superusers (Django admin) can also edit.
        if getattr(user, "is_superuser", False):
            return True
        if not user.is_club_admin:
            return False
        # Resolve the club from the object. Court/Schedule resolve via
        # .club; Club itself is the club.
        club = obj if isinstance(obj, Club) else getattr(obj, "club", None)
        if club is None:
            return False
        return club.created_by_id == user.id


class IsClubAdminOrSuperAdmin(IsClubAdmin):
    """Alias kept for readability at call sites that want to spell out
    "either club_admin OR super_admin" explicitly.
    """

    # Inherits behaviour from IsClubAdmin (super_admin short-circuits).
    pass
