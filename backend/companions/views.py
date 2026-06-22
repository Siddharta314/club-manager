"""Companion endpoints.

Endpoints
---------
- ``POST /api/v1/matches/{id}/companions/`` — register a companion
  on the given match. The request user must be a signed-up player
  on the match, OR a club admin (sponsor or admin gate). The
  match must not be full.
- ``DELETE /api/v1/companions/{id}/`` — remove a companion. Only
  the original sponsor or a club admin can remove; the service
  itself is permission-free.

Both endpoints are ``APIView``s rather than ``ViewSet`` actions
because they live on different URL shapes (collection POST vs.
item DELETE) and don't share a single resource cleanly.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Companion
from .serializers import CompanionSerializer
from .services import register_companion, remove_companion


class RegisterCompanionView(APIView):
    """``POST /api/v1/matches/{id}/companions/`` — register a companion.

    Permission gate: the request user must be either a MatchPlayer
    on this match (the "sponsor" relationship) OR a club admin of
    the match's court. Outsiders get 403.

    Validation:
    - Name + level come from the request body; the serializer
      rejects empty names and out-of-range levels with 400.
    - Service-layer checks: sponsor must be a player, match must
      not be full. ``ValueError`` maps to 400.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, pk: int) -> Response:
        from matches.models import Match

        try:
            match = Match.objects.select_related("match_slot__court__club").get(pk=pk)
        except Match.DoesNotExist:
            return Response(
                {"detail": "Match not found"}, status=status.HTTP_404_NOT_FOUND
            )

        club = match.slot.court.club
        is_admin = club.is_admin(request.user)
        is_player = match.players.filter(user=request.user).exists()
        if not (is_admin or is_player):
            raise PermissionDenied("Only players or admins can register companions")

        serializer = CompanionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # When the caller is an admin but not a player, they can't be
        # the sponsor (the service enforces sponsor-must-be-player).
        # We default the sponsor to the match host — the natural
        # "I'm registering on behalf of a player" path for admins.
        # Players sponsor their own companions directly.
        if is_player:
            sponsor = request.user
        else:
            sponsor = match.host

        try:
            companion = register_companion(
                match=match,
                sponsor=sponsor,
                name=serializer.validated_data["name"],
                level=serializer.validated_data["level"],
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            CompanionSerializer(companion).data,
            status=status.HTTP_201_CREATED,
        )


class CompanionDetailView(APIView):
    """``DELETE /api/v1/companions/{id}/`` — remove a companion.

    Permission gate: the original sponsor OR a club admin. The
    service layer's ``remove_companion`` is permission-free; the
    view enforces the gate before calling.
    """

    permission_classes = [IsAuthenticated]

    def delete(self, request: Request, pk: int) -> Response:
        try:
            companion = Companion.objects.select_related(
                "match__match_slot__court__club"
            ).get(pk=pk)
        except Companion.DoesNotExist:
            return Response(
                {"detail": "Companion not found"}, status=status.HTTP_404_NOT_FOUND
            )

        club = companion.match.slot.court.club
        is_admin = club.is_admin(request.user)
        is_sponsor = companion.sponsored_by_id == request.user.pk
        if not (is_admin or is_sponsor):
            raise PermissionDenied("Only sponsor or admin can remove companion")

        remove_companion(companion)
        return Response(status=status.HTTP_204_NO_CONTENT)
