"""Match lifecycle endpoints.

Endpoints
---------
- ``POST /api/v1/slots/{slot_id}/match/`` — create a Match from an
  empty slot (host-first signup). The request user becomes the
  host; their level defines the initial range.
- ``GET  /api/v1/matches/{id}/`` — full match detail (players,
  companions, capacity).
- ``POST /api/v1/matches/{id}/join/`` — signup as a player.
  Honours the level range; out-of-range returns 400.
- ``POST /api/v1/matches/{id}/leave/`` — leave the match.
  The host cannot leave their own match (400).
- ``POST /api/v1/matches/{id}/cancel/`` — admin-only cancel. Sets
  ``is_cancelled = True``; new signups are then blocked.
- ``POST /api/v1/matches/{id}/override-add/`` — admin-only add
  outside the level range. Body: ``{"user_id": <int>}``.

Permissions
-----------
Anonymous users get 401 from the global ``IsAuthenticated`` default.
Mutation endpoints re-check the club's admin membership through
``Club.is_admin`` to keep the gate explicit at the view layer
(rather than relying on a permission class — the Match model doesn't
have a direct ``club`` FK so ``IsClubAdmin``'s object-level
resolution would need extra work).
"""
from __future__ import annotations

from typing import Any

from django.utils import timezone
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from match_slots.models import MatchSlot
from players.models import User

from .models import Match
from .serializers import MatchSerializer
from .services import create_match_from_slot, join_match, leave_match


# ---------------------------------------------------------------------------
# Create from slot
# ---------------------------------------------------------------------------
class CreateMatchFromSlotView(APIView):
    """``POST /api/v1/slots/{slot_id}/match/`` — first signup creates the Match.

    The view refuses to create a match on a slot that is already
    booked, in the past, or missing. All other validation (host
    level, etc.) is delegated to the service layer; ``ValueError``
    is mapped to 400.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, slot_id: int) -> Response:
        try:
            slot = MatchSlot.objects.select_related("court__club").get(pk=slot_id)
        except MatchSlot.DoesNotExist:
            return Response(
                {"detail": "Slot not found"}, status=status.HTTP_404_NOT_FOUND
            )

        if slot.booked_match is not None:
            return Response(
                {"detail": "Slot already booked"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # The slot must start in the future. Past slots can't accept
        # new signups even if they slipped through the listing filter
        # (admin can still create a match via the admin shell if they
        # really want to — that's a separate concern).
        if slot.start_time <= timezone.now():
            return Response(
                {"detail": "Slot start time has passed"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            match = create_match_from_slot(slot=slot, host=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            MatchSerializer(match).data,
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------
class MatchDetailView(generics.RetrieveAPIView):
    """``GET /api/v1/matches/{id}/`` — full match detail.

    We prefetch the ``players`` and ``companions`` reverse relations
    so the serializer doesn't issue N+1 queries on read.
    """

    permission_classes = [IsAuthenticated]
    queryset = (
        Match.objects.select_related("match_slot__court__club")
        .prefetch_related("players__user", "companions")
    )
    serializer_class = MatchSerializer


# ---------------------------------------------------------------------------
# Join / leave
# ---------------------------------------------------------------------------
class JoinMatchView(APIView):
    """``POST /api/v1/matches/{id}/join/`` — self-signup as a player.

    The view is intentionally simple: it loads the match (404 on
    miss) and delegates the level / capacity / cancellation
    validation to the service. Idempotent: re-joining returns 200
    with the current state and no new row is created.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: int) -> Response:
        try:
            match = Match.objects.get(pk=pk)
        except Match.DoesNotExist:
            return Response(
                {"detail": "Match not found"}, status=status.HTTP_404_NOT_FOUND
            )

        try:
            join_match(match=match, user=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(MatchSerializer(match).data, status=status.HTTP_200_OK)


class LeaveMatchView(APIView):
    """``POST /api/v1/matches/{id}/leave/`` — leave the match.

    The service layer raises ``ValueError`` if the user is the host;
    we map that to 400. Other cases (idempotent no-op) return 204.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: int) -> Response:
        try:
            match = Match.objects.get(pk=pk)
        except Match.DoesNotExist:
            return Response(
                {"detail": "Match not found"}, status=status.HTTP_404_NOT_FOUND
            )

        try:
            leave_match(match=match, user=request.user)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Admin: cancel / override-add
# ---------------------------------------------------------------------------
def _require_club_admin(user: Any, match: Match) -> None:
    """Raise ``PermissionDenied`` if ``user`` is not an admin of the match's club.

    Centralised so the cancel and override-add views share the same
    gate. ``Match.slot.court.club`` is the path back to the club;
    we use ``Club.is_admin`` which already handles the M2M check.
    """
    club = match.slot.court.club
    if not club.is_admin(user):
        raise PermissionDenied("Only club admins can perform this action")


class CancelMatchView(APIView):
    """``POST /api/v1/matches/{id}/cancel/`` — admin-only cancel."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: int) -> Response:
        try:
            match = Match.objects.select_related("match_slot__court__club").get(pk=pk)
        except Match.DoesNotExist:
            return Response(
                {"detail": "Match not found"}, status=status.HTTP_404_NOT_FOUND
            )

        _require_club_admin(request.user, match)
        match.is_cancelled = True
        match.save(update_fields=["is_cancelled"])
        return Response(MatchSerializer(match).data, status=status.HTTP_200_OK)


class AdminAddPlayerView(APIView):
    """``POST /api/v1/matches/{id}/override-add/`` — admin-only add outside the level range.

    Body: ``{"user_id": <int>}``. The service's ``force=True`` flag
    bypasses the level-range check; capacity and cancellation
    invariants still apply.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: int) -> Response:
        try:
            match = Match.objects.select_related("match_slot__court__club").get(pk=pk)
        except Match.DoesNotExist:
            return Response(
                {"detail": "Match not found"}, status=status.HTTP_404_NOT_FOUND
            )

        _require_club_admin(request.user, match)

        target_user_id = request.data.get("user_id")
        if not target_user_id:
            return Response(
                {"detail": "user_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            target_user = User.objects.get(pk=target_user_id)
        except User.DoesNotExist:
            return Response(
                {"detail": "User not found"}, status=status.HTTP_404_NOT_FOUND
            )

        try:
            join_match(match=match, user=target_user, force=True)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(MatchSerializer(match).data, status=status.HTTP_200_OK)
