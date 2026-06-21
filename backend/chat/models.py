"""Chat app — per-match polling chat.

A `ChatMessage` is a single message in a match's chat thread. Each message
is authored by either a signed-up user (`author_user`) or a companion
(`author_companion`), never both and never neither — the XOR invariant is
enforced by a CHECK constraint and a model-level validator.

The polling endpoint (`GET /matches/{id}/messages/?since={last_id}`) ships
in PR 4 along with the participant-only access guard. This module owns
the data model only.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class ChatMessage(models.Model):
    """A single chat message in a match's thread."""

    match = models.ForeignKey(
        "matches.Match",
        on_delete=models.CASCADE,
        related_name="messages",
    )
    author_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_messages_authored",
        null=True,
        blank=True,
    )
    author_companion = models.ForeignKey(
        "companions.Companion",
        on_delete=models.CASCADE,
        related_name="chat_messages_authored",
        null=True,
        blank=True,
    )
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "chat_chatmessage"
        constraints = [
            # Exactly one of author_user / author_companion must be set.
            models.CheckConstraint(
                condition=(
                    Q(author_user__isnull=False, author_companion__isnull=True)
                    | Q(author_user__isnull=True, author_companion__isnull=False)
                ),
                name="chat_chatmessage_author_xor",
            ),
        ]
        indexes = [
            models.Index(fields=["match", "id"], name="chat_msg_match_id_idx"),
            models.Index(fields=["created_at"], name="chat_msg_created_idx"),
        ]
        ordering = ("id",)

    def __str__(self):
        who = self.author_user or self.author_companion
        return f"{who}: {self.text[:40]}"

    def clean(self):
        """Reject messages with zero or two authors at the model layer."""
        super().clean()
        has_user = self.author_user_id is not None
        has_companion = self.author_companion_id is not None
        if has_user == has_companion:  # both True or both False
            raise ValidationError(
                {"author_user": "Exactly one of author_user or author_companion must be set."}
            )