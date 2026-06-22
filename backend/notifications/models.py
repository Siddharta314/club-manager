"""Notifications app — NotificationLog model.

A `NotificationLog` is the audit trail for every push / email attempt
fired by the Q2 worker. PR 4 adds the worker task
(`notifications.tasks.send_notification`) that creates these rows. This
module owns the data model only.
"""
from django.conf import settings
from django.db import models


class NotificationLog(models.Model):
    """Per-attempt log row for push / email dispatches."""

    class EventType(models.TextChoices):
        MATCH_CREATED = "match_created", "Match created"
        MATCH_JOINED = "player_joined", "Player joined"
        MATCH_LEFT = "match_left", "Player left"
        MATCH_CANCELLED = "match_cancelled", "Match cancelled"

    class Channel(models.TextChoices):
        PUSH = "push", "Expo Push"
        EMAIL = "email", "Resend email"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped (opt-out)"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_logs",
    )
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    channel = models.CharField(max_length=16, choices=Channel.choices)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    error = models.TextField(blank=True, default="")
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "notifications_notificationlog"
        indexes = [
            models.Index(fields=["user", "created_at"], name="notif_user_created_idx"),
            models.Index(fields=["status"], name="notif_status_idx"),
            models.Index(fields=["event_type"], name="notif_event_idx"),
        ]
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.event_type} {self.channel} → {self.user} [{self.status}]"

    def mark_sent(self):
        from django.utils import timezone

        self.status = self.Status.SENT
        self.sent_at = timezone.now()
        self.save(update_fields=["status", "sent_at", "updated_at"])

    def mark_failed(self, error: str):
        self.status = self.Status.FAILED
        self.error = error
        self.save(update_fields=["status", "error", "updated_at"])

    def mark_skipped(self, reason: str = ""):
        self.status = self.Status.SKIPPED
        if reason:
            self.error = reason
        self.save(update_fields=["status", "error", "updated_at"])