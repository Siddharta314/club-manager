"""DRF viewsets for the clubs app.

Five viewsets / views:

- ``ClubViewSet``: list / retrieve / create / update / destroy.
  Anyone authenticated can list and retrieve; only the club admins
  (members of ``Club.admins``) can mutate. On create the request user
  is auto-added to ``admins`` and their role is promoted to
  ``club_admin``.
- ``CourtViewSet``: nested under club. Only club admin can mutate.
- ``ScheduleViewSet``: nested under court. Only club admin can
  mutate. Saving a Schedule triggers slot generation via the
  post_save signal wired in ``signals.py``.
- ``ClubSlotListView``: read-only listing of future ``MatchSlot``
  rows for a given date.
- ``ClubAdminViewSet``: secondary admin add / remove endpoints
  (``POST /clubs/{id}/admins/`` and ``DELETE /clubs/{id}/admins/{user_id}/``).
  Only existing admins can call these; the creator cannot be
  demoted and the last admin cannot be removed.

The slot-list endpoint uses a ``GenericAPIView`` rather than a
``ModelViewSet`` because it's a custom action shape (``GET
/clubs/{id}/slots/?date=YYYY-MM-DD``) — DRF's routers don't support
that nested-list syntax without ``@action(detail=True)``.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.exceptions import ParseError, ValidationError
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from match_slots.models import MatchSlot
from match_slots.serializers import MatchSlotSerializer  # type: ignore[import]
from players.models import User

from .models import Club, Court, Schedule
from .permissions import IsAuthenticatedReadOnly, IsClubAdmin
from .serializers import (
    ClubSerializer,
    ClubWriteSerializer,
    CourtSerializer,
    ScheduleSerializer,
)


# ---------------------------------------------------------------------------
# ClubViewSet
# ---------------------------------------------------------------------------
class ClubViewSet(viewsets.ModelViewSet):
    """CRUD over clubs.

    List / retrieve use the nested-court ``ClubSerializer``; create /
    update use ``ClubWriteSerializer`` and return the read shape on
    success so the mobile client gets the full club back in one round
    trip.
    """

    queryset = Club.objects.all().prefetch_related("courts")
    permission_classes = [IsAuthenticatedReadOnly, IsClubAdmin]
    lookup_field = "pk"

    def get_serializer_class(self) -> type:
        if self.action in {"create", "update", "partial_update"}:
            return ClubWriteSerializer
        return ClubSerializer

    def get_queryset(self) -> Any:
        qs = super().get_queryset()
        # Always prefetch courts for the read serializer to avoid N+1.
        return qs.prefetch_related("courts")

    def perform_create(self, serializer: ClubWriteSerializer) -> None:
        # The creator becomes the club admin. We:
        # 1. Save with ``created_by`` (audit field).
        # 2. Add the creator to the M2M ``admins`` set (gates the
        #    IsClubAdmin object-level permission).
        # 3. Promote the creator's role to ``club_admin`` so global
        #    role-based filtering (e.g. mobile admin tab) works.
        club: Club = serializer.save(created_by=self.request.user)
        club.admins.add(self.request.user)
        creator: User = self.request.user
        if creator.role != User.Role.CLUB_ADMIN:
            creator.role = User.Role.CLUB_ADMIN
            creator.save(update_fields=["role"])

    @transaction.atomic
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        read = ClubSerializer(serializer.instance, context=self.get_serializer_context())
        return Response(read.data, status=status.HTTP_201_CREATED)

    @transaction.atomic
    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        read = ClubSerializer(instance, context=self.get_serializer_context())
        return Response(read.data)

    @transaction.atomic
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self.update(request, *args, partial=True, **kwargs)


# ---------------------------------------------------------------------------
# CourtViewSet
# ---------------------------------------------------------------------------
class CourtViewSet(viewsets.ModelViewSet):
    """Courts nested under a club.

    URL: ``/clubs/{club_pk}/courts/`` and ``/clubs/{club_pk}/courts/{pk}/``.
    """

    serializer_class = CourtSerializer
    permission_classes = [IsAuthenticatedReadOnly, IsClubAdmin]

    def get_queryset(self) -> Any:
        club_pk = self.kwargs.get("club_pk")
        return Court.objects.filter(club_id=club_pk).order_by("id")

    def perform_create(self, serializer: CourtSerializer) -> None:
        club = get_object_or_404(Club, pk=self.kwargs.get("club_pk"))
        # Permission object-check is enforced by IsClubAdmin when the
        # view resolves the parent. We do an explicit check here so the
        # API returns 403 rather than 404 on a non-admin attempting a
        # nested create.
        self.check_object_permissions(self.request, club)
        serializer.save(club=club)


# ---------------------------------------------------------------------------
# ScheduleViewSet
# ---------------------------------------------------------------------------
class ScheduleViewSet(viewsets.ModelViewSet):
    """Schedules nested under a court.

    URL: ``/clubs/{club_pk}/courts/{court_pk}/schedule/``. Saving a
    Schedule triggers ``match_slots.services.generate_slots`` via the
    ``post_save`` signal wired in ``clubs.signals``.
    """

    serializer_class = ScheduleSerializer
    permission_classes = [IsAuthenticatedReadOnly, IsClubAdmin]

    def get_queryset(self) -> Any:
        return Schedule.objects.filter(court_id=self.kwargs.get("court_pk")).order_by(
            "weekday", "start_time"
        )

    def perform_create(self, serializer: ScheduleSerializer) -> None:
        court = get_object_or_404(Court, pk=self.kwargs.get("court_pk"))
        club = court.club
        self.check_object_permissions(self.request, club)
        serializer.save(court=court)


# ---------------------------------------------------------------------------
# ClubSlotListView
# ---------------------------------------------------------------------------
class ClubSlotListView(GenericAPIView):
    """GET /clubs/{id}/slots/?date=YYYY-MM-DD — future slots for a club.

    Filters by ``date`` if supplied; falls back to "today onwards"
    when the query string is missing. Always filters out past slots
    so the mobile client never has to.
    """

    serializer_class = MatchSlotSerializer
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, pk: str) -> Response:
        club = get_object_or_404(Club, pk=pk)
        date_str = request.query_params.get("date")
        target_date = self._parse_date(date_str)
        # The date is interpreted as a local-time calendar day; we
        # build the [start, end) window in the project timezone and
        # filter on it.
        if target_date is None:
            start_dt = timezone.now()
        else:
            start_dt = timezone.make_aware(
                datetime.combine(target_date, time.min),
                timezone.get_current_timezone(),
            )
            if start_dt < timezone.now():
                # If a past date is requested, fall back to "now" so
                # the client always sees future slots.
                start_dt = timezone.now()

        qs = (
            MatchSlot.objects.filter(court__club_id=club.id, start_time__gte=start_dt)
            .select_related("court")
            .order_by("start_time")
        )
        if target_date is not None:
            end_dt = start_dt + timedelta(days=1)
            qs = qs.filter(start_time__lt=end_dt)

        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    @staticmethod
    def _parse_date(raw: str | None) -> date | None:
        if raw is None or raw == "":
            return None
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ParseError("date must be YYYY-MM-DD") from exc


# ---------------------------------------------------------------------------
# ClubAdminView (secondary admin add/remove)
# ---------------------------------------------------------------------------
class ClubAdminView(APIView):
    """Secondary admin add/remove endpoints.

    ``POST /clubs/{pk}/admins/`` with body ``{"user_id": <int>}`` —
    promote a user to admin of this club. Only existing admins may
    call; the target user must already belong to the club (via
    ``User.club``); if their role is ``player`` it is bumped to
    ``club_admin``.

    ``DELETE /clubs/{pk}/admins/{user_id}/`` — remove a user from the
    admins M2M. Only existing admins may call; the creator cannot be
    demoted; the last admin cannot be removed.

    The view deliberately uses ``APIView`` rather than a ``ViewSet``
    because the two endpoints have different URL shapes (collection
    POST vs item DELETE) and DRF's router wouldn't add them naturally.
    """

    permission_classes = [IsAuthenticated, IsClubAdmin]

    def post(self, request: Request, pk: str) -> Response:
        club = get_object_or_404(Club, pk=pk)
        self.check_object_permissions(request, club)
        user_id = _require_user_id(request.data)
        target = get_object_or_404(User, pk=user_id)
        # The target must already be a member of this club. Per the
        # spec, User.club is 1:1; a user belonging to a different
        # club cannot be promoted here.
        if target.club_id != club.id:
            raise ValidationError(
                {"user_id": "User does not belong to this club."}
            )
        # Idempotent: re-adding an existing admin is a no-op (still
        # returns 200 so the mobile client can retry safely).
        if not club.is_admin(target):
            club.admins.add(target)
        if target.role == User.Role.PLAYER:
            target.role = User.Role.CLUB_ADMIN
            target.save(update_fields=["role"])
        return Response(
            {
                "club_id": club.id,
                "user_id": target.id,
                "is_admin": True,
            },
            status=status.HTTP_200_OK,
        )

    def delete(self, request: Request, pk: str, user_id: int) -> Response:
        club = get_object_or_404(Club, pk=pk)
        self.check_object_permissions(request, club)
        target = get_object_or_404(User, pk=user_id)
        # The creator (created_by) is permanent — the original signer
        # of the club cannot be demoted via the admin endpoint.
        if club.created_by_id == target.id:
            raise ValidationError(
                {"user_id": "The creator cannot be removed as admin."}
            )
        # Last-admin guard: ensure at least one admin remains after
        # removal. We compare against the current admin count so the
        # check is accurate under concurrent admins.
        if club.admins.count() <= 1:
            raise ValidationError(
                {"user_id": "Cannot remove the last admin of a club."}
            )
        # Idempotent: removing a non-admin is a no-op.
        if club.is_admin(target):
            club.admins.remove(target)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _require_user_id(payload: Any) -> int:
    """Extract and validate the ``user_id`` field from a request body."""
    if not isinstance(payload, dict):
        raise ValidationError({"user_id": "Request body must be a JSON object."})
    raw = payload.get("user_id")
    if raw is None:
        raise ValidationError({"user_id": "This field is required."})
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"user_id": "Must be an integer."}) from exc
