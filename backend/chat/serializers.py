"""Chat serializers for per-match polling messages.

Two serializers:

- ``ChatMessageSerializer`` — read shape for both ``GET`` (list) and
  ``POST`` (single response) of ``/matches/{id}/messages/``. Exposes the
  author id (user or companion) plus a derived ``author_display_name``
  so the mobile client can render the bubble without a second round
  trip.
- ``ChatMessageCreateSerializer`` — thin write shape for ``POST``. The
  body only carries ``text``; ``match``, ``author_user`` and
  ``author_companion`` are populated by the view from the URL and
  ``request.user``.

The text validator enforces the same rules as the model layer
(non-empty after strip, ≤1000 chars) and surfaces them as DRF 400s
rather than the model's ``full_clean`` path.
"""
from __future__ import annotations

from rest_framework import serializers

from chat.models import ChatMessage


class ChatMessageSerializer(serializers.ModelSerializer):
    """Read serializer for chat messages.

    The author fields are intentionally split (one user id, one
    companion id, plus a derived display name) so the mobile client
    can render any combination without a separate user/companion
    lookup. Exactly one of ``author_user_id`` / ``author_companion_id``
    is non-null per the model's XOR invariant.
    """

    author_user_id = serializers.IntegerField(
        source="author_user_id", read_only=True, allow_null=True
    )
    author_companion_id = serializers.IntegerField(
        source="author_companion_id", read_only=True, allow_null=True
    )
    author_display_name = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = [
            "id",
            "match_id",
            "author_user_id",
            "author_companion_id",
            "author_display_name",
            "text",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "match_id",
            "author_user_id",
            "author_companion_id",
            "author_display_name",
            "created_at",
        ]

    def get_author_display_name(self, obj: ChatMessage) -> str:
        """Pick the best human-readable name from whichever author is set.

        Falls back to ``"Unknown"`` if both are missing (shouldn't
        happen given the XOR invariant, but we keep the safe
        fallback so the client never receives ``None``).
        """
        if obj.author_user is not None:
            full_name = obj.author_user.get_full_name()
            return full_name or obj.author_user.email or "Unknown"
        if obj.author_companion is not None:
            return obj.author_companion.name
        return "Unknown"


class ChatMessageCreateSerializer(serializers.ModelSerializer):
    """Write serializer for posting a chat message.

    Only ``text`` is accepted; the view sets the author and match FKs
    from URL + ``request.user``. The validator rejects empty text
    after trim and texts longer than 1000 characters.
    """

    class Meta:
        model = ChatMessage
        fields = ["text"]

    def validate_text(self, value: str) -> str:
        """Strip and bound-check the message body."""
        text = (value or "").strip()
        if not text:
            raise serializers.ValidationError("Message text must not be empty")
        if len(text) > 1000:
            raise serializers.ValidationError(
                "Message text must be 1000 characters or fewer"
            )
        return text