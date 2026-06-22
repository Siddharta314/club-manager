"""Chat polling + create endpoints.

Endpoints
---------
- ``GET  /api/v1/matches/{id}/messages/?since={last_id}`` — list
  messages newer than ``last_id``, ordered ascending by id.
- ``POST /api/v1/matches/{id}/messages/`` — post a message as the
  request user.

Both endpoints share the same permission gate
(``chat.services.user_can_access_match_chat``): the user must be a
signed-up player on the match OR sponsor a companion on the match.
Outsiders get 403 from DRF's ``PermissionDenied``.

The ``POST`` endpoint honours the same ``Idempotency-Key`` contract
as ``matches.views.JoinMatchView`` so the mobile client can retry a
mutated POST on a flaky network without re-sending the same
message. The helper is imported from ``matches.idempotency`` — a
deliberate cross-app dependency within the same Django project so
the cache backend + scoping rules stay in one module.
"""
from __future__ import annotations

from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from chat.models import ChatMessage
from chat.serializers import ChatMessageCreateSerializer, ChatMessageSerializer
from chat.services import list_messages, post_message, user_can_access_match_chat
from matches.idempotency import (
    IDEMPOTENCY_HEADER,
    get_cached as get_idempotent_response,
)
from matches.idempotency import store as store_idempotent_response
from matches.models import Match


class ChatMessageListView(APIView):
    """``GET /api/v1/matches/{id}/messages/`` + ``POST`` to the same URL.

    GET is the polling endpoint used by the mobile chat screen every
    5s (see ``useChat`` hook in the frontend). The ``since`` query
    parameter holds the largest id the client already saw; missing
    or non-numeric ``since`` is handled as documented below.

    POST lets a signed-up user send a message; the view sets the
    author to ``request.user`` (companions can't authenticate, so
    they don't post directly — the sponsor posts on their behalf if
    needed in a future iteration).

    Both methods go through the same access check.
    """

    permission_classes = [IsAuthenticated]

    @staticmethod
    def _get_match_or_404(pk: int) -> Match:
        """Fetch the match with its slot/court/club path eagerly loaded."""
        try:
            return Match.objects.select_related("slot__court__club").get(pk=pk)
        except Match.DoesNotExist as exc:
            raise NotFound("Match not found") from exc

    def get(self, request: Request, pk: int) -> Response:
        """Return chat messages for the match.

        Query params:

        - ``since`` — optional int; only messages with id > since are
          returned. A non-numeric value yields 400. Missing or empty
          means "all messages, capped at the limit".
        """
        match = self._get_match_or_404(pk)
        if not user_can_access_match_chat(request.user, match):
            raise PermissionDenied("You cannot read this chat")

        since_id_raw = request.query_params.get("since")
        since_id: int | None = None
        if since_id_raw is not None and since_id_raw != "":
            try:
                since_id = int(since_id_raw)
            except (TypeError, ValueError):
                return Response(
                    {"detail": "Invalid since parameter"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        messages = list_messages(match, since_id=since_id)
        return Response(
            ChatMessageSerializer(messages, many=True).data,
            status=status.HTTP_200_OK,
        )

    def post(self, request: Request, pk: int) -> Response:
        """Post a chat message as ``request.user``.

        Honours the ``Idempotency-Key`` header (same contract as
        ``matches.views.JoinMatchView``) so a mobile retry on a
        flaky network doesn't double-post. The cached response is
        returned verbatim on retry.
        """
        idem_key = request.headers.get(IDEMPOTENCY_HEADER, "")

        if idem_key:
            cached = get_idempotent_response(idem_key, request)
            if cached is not None:
                cached_status, cached_body = cached
                return Response(cached_body, status=cached_status)

        match = self._get_match_or_404(pk)
        if not user_can_access_match_chat(request.user, match):
            raise PermissionDenied("You cannot post to this chat")

        serializer = ChatMessageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        text = serializer.validated_data["text"]

        # The author is always the requesting user. Companions cannot
        # post directly because they don't authenticate.
        message = post_message(match, author_user=request.user, text=text)
        body = ChatMessageSerializer(message).data
        response = Response(body, status=status.HTTP_201_CREATED)

        if idem_key:
            store_idempotent_response(
                idem_key, request, response.status_code, body
            )
        return response