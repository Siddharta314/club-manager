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

from django.db.models import Count, F
from django.http import Http404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from clubs.models import Club
from match_slots.models import MatchSlot
from players.models import User

from .idempotency import IDEMPOTENCY_HEADER, get_cached as get_idempotent_response
from .idempotency import store as store_idempotent_response
from .models import Match
from .serializers import MatchSerializer
from .services import cancel_match, create_match_from_slot, join_match, leave_match


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
# List
# ---------------------------------------------------------------------------
class MatchListView(generics.ListAPIView):
    """``GET /api/v1/clubs/<int:pk>/matches/`` — open matches at a club.

    Filter contract (server-side, source of truth per REQ-MATCH-002):
    - ``match_slot__court__club_id == pk``
    - ``is_cancelled == False``
    - ``player_count + companion_count < 4`` (i.e., capacity is open)

    Order: ``match_slot__start_time`` ASC (earliest first per REQ-MATCH-003).

    Query optimisation:
    - ``select_related("match_slot__court")`` joins through the slot to the
      court so the new ``court`` field on ``MatchSerializer`` doesn't
      trigger N+1.
    - ``prefetch_related("players__user", "companions")`` covers the
      reverse-relation walks in the serializer.

    ``slot`` is a Python property, NOT an ORM field — we MUST use
    ``match_slot__court__club_id`` (not ``slot__court__club_id``), matching
    the existing ``MatchDetailView`` pattern.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = MatchSerializer
    # The spec requires a plain JSON array of match objects
    # (``REQ-MATCH-001``: "a JSON array of objects"). The project's
    # default is ``PageNumberPagination`` (wraps the list in
    # ``{count, next, previous, results}``); we opt out here so the
    # mobile client's `useQuery<Match[]>` type stays accurate without
    # unwrapping ``results`` at every call site.
    pagination_class = None

    def get_queryset(self):
        club_id = self.kwargs["pk"]
        if not Club.objects.filter(pk=club_id).exists():
            raise Http404("Club not found")
        return (
            Match.objects
            .select_related("match_slot__court")
            .prefetch_related("players__user", "companions")
            .annotate(
                player_count=Count("players", distinct=True),
                companion_count=Count("companions", distinct=True),
            )
            .annotate(total=F("player_count") + F("companion_count"))
            .filter(
                match_slot__court__club_id=club_id,
                is_cancelled=False,
                total__lt=4,
            )
            .order_by("match_slot__start_time")
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
    validation to the service. Idempotent in two senses:

    - Service-layer: re-joining the same user returns the existing
      ``MatchPlayer`` row instead of creating a duplicate.
    - HTTP-layer (PR 3.1): clients can send an ``Idempotency-Key``
      header to opt into response caching — a duplicate POST with
      the same key returns the original response verbatim, so the
      mobile retry-on-timeout path doesn't re-create state.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: int) -> Response:
        idem_key = request.headers.get(IDEMPOTENCY_HEADER, "")

        # Cached-retry path — return the original response verbatim.
        if idem_key:
            cached = get_idempotent_response(idem_key, request)
            if cached is not None:
                cached_status, cached_body = cached
                return Response(cached_body, status=cached_status)

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
        body = MatchSerializer(match).data
        response = Response(body, status=status.HTTP_200_OK)

        if idem_key:
            store_idempotent_response(
                idem_key, request, response.status_code, body
            )
        return response


class LeaveMatchView(APIView):
    """``POST /api/v1/matches/{id}/leave/`` — leave the match.

    The service layer raises ``ValueError`` if the user is the host;
    we map that to 400. Other cases (idempotent no-op) return 204.

    Like ``JoinMatchView``, accepts an ``Idempotency-Key`` header for
    mobile retry safety. A 204 response has no body, but we still
    cache ``(204, None)`` so a retry sees the same outcome without
    needing to know the original was body-less.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: int) -> Response:
        idem_key = request.headers.get(IDEMPOTENCY_HEADER, "")

        if idem_key:
            cached = get_idempotent_response(idem_key, request)
            if cached is not None:
                cached_status, cached_body = cached
                # 204 responses carry no body; the cached body is ``None``.
                return Response(cached_body, status=cached_status)

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
        response = Response(status=status.HTTP_204_NO_CONTENT)

        if idem_key:
            store_idempotent_response(
                idem_key, request, response.status_code, None
            )
        return response


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
        cancel_match(match)
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
