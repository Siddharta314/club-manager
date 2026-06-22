"""Chat business logic — participant access checks + message persistence.

These functions are pure (no Django request/response objects) so they
can be unit-tested in isolation. The view layer wraps them in DRF
permission checks and HTTP error mapping.

Three responsibilities:

- ``user_can_access_match_chat`` — gate for both GET and POST. A user
  can read/write the chat of a match iff they are a signed-up player
  on the match, OR they sponsor at least one companion on the match.
  Outsiders get 403 from the view layer.
- ``list_messages`` — paginated reader for the polling endpoint.
  Supports a ``since_id`` cursor for the client's "give me everything
  after my last seen id" pattern.
- ``post_message`` — write helper. Enforces the XOR author invariant
  in code (the model layer also enforces it via CHECK constraint and
  ``clean()``).
"""
from __future__ import annotations

from typing import Any

from chat.models import ChatMessage
from companions.models import Companion
from matches.models import Match, MatchPlayer


def user_can_access_match_chat(user: Any, match: Match) -> bool:
    """Return True if ``user`` is allowed to read/write the match chat.

    Two paths grant access:

    1. The user is a ``MatchPlayer`` on the match (signed up directly).
    2. The user sponsors at least one ``Companion`` on the match
       (their registered companion can participate in the chat).

    Anonymous users and users with no relation to the match both
    return ``False``; the view maps that to ``PermissionDenied``.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if not getattr(user, "pk", None):
        return False
    if MatchPlayer.objects.filter(match=match, user=user).exists():
        return True
    if Companion.objects.filter(match=match, sponsored_by=user).exists():
        return True
    return False


def list_messages(
    match: Match,
    since_id: int | None = None,
    limit: int = 50,
) -> list[ChatMessage]:
    """Return chat messages for a match, ordered ascending by id.

    ``since_id`` is the cursor for the polling endpoint — pass the
    largest id the client has already seen to get only newer
    messages. ``limit`` caps the response so a long-idle client
    doesn't pull an unbounded batch; the mobile client should
    always resume with the highest id it just received.
    """
    qs = ChatMessage.objects.filter(match=match)
    if since_id is not None:
        qs = qs.filter(id__gt=since_id)
    return list(qs.order_by("id")[:limit])


def post_message(
    match: Match,
    *,
    author_user: Any = None,
    author_companion: Any = None,
    text: str,
) -> ChatMessage:
    """Persist a new chat message.

    Exactly one of ``author_user`` / ``author_companion`` must be set.
    The model layer enforces the same invariant via CHECK constraint
    + ``clean()``; we also enforce it here so callers get a clear
    ``ValueError`` instead of an ``IntegrityError`` from the DB.

    For the MVP HTTP endpoint, the view always passes ``author_user``;
    companions cannot post directly (they don't authenticate).
    """
    if (author_user is None) == (author_companion is None):
        raise ValueError(
            "Exactly one of author_user or author_companion must be set"
        )
    return ChatMessage.objects.create(
        match=match,
        author_user=author_user,
        author_companion=author_companion,
        text=text,
    )