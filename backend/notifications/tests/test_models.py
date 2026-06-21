"""Tests for the notifications app — NotificationLog model.

Covers basic creation, the status transition helpers, and the
event_type/channel choice enforcement.
"""
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from notifications.models import NotificationLog
from players.models import User


@pytest.mark.django_db
class TestNotificationLog:
    def test_basic_creation(self):
        user = User.objects.create(username="n_user", email="n@example.com")
        log = NotificationLog.objects.create(
            user=user,
            event_type=NotificationLog.EventType.MATCH_JOINED,
            channel=NotificationLog.Channel.PUSH,
        )
        assert log.status == NotificationLog.Status.PENDING
        assert log.sent_at is None
        assert log.error == ""

    def test_mark_sent_sets_status_and_timestamp(self):
        user = User.objects.create(username="n_s", email="ns@example.com")
        log = NotificationLog.objects.create(
            user=user,
            event_type=NotificationLog.EventType.MATCH_CREATED,
            channel=NotificationLog.Channel.EMAIL,
        )
        before = timezone.now()
        log.mark_sent()
        log.refresh_from_db()
        assert log.status == NotificationLog.Status.SENT
        assert log.sent_at is not None
        assert log.sent_at >= before - timedelta(seconds=1)

    def test_mark_failed_records_error(self):
        user = User.objects.create(username="n_f", email="nf@example.com")
        log = NotificationLog.objects.create(
            user=user,
            event_type=NotificationLog.EventType.MATCH_LEFT,
            channel=NotificationLog.Channel.PUSH,
        )
        log.mark_failed("invalid push token")
        log.refresh_from_db()
        assert log.status == NotificationLog.Status.FAILED
        assert log.error == "invalid push token"

    def test_mark_skipped_records_opt_out_reason(self):
        user = User.objects.create(username="n_k", email="nk@example.com")
        log = NotificationLog.objects.create(
            user=user,
            event_type=NotificationLog.EventType.MATCH_JOINED,
            channel=NotificationLog.Channel.EMAIL,
        )
        log.mark_skipped("notify_email=false")
        log.refresh_from_db()
        assert log.status == NotificationLog.Status.SKIPPED
        assert log.error == "notify_email=false"

    def test_invalid_event_type_rejected_on_full_clean(self):
        user = User.objects.create(username="n_bad", email="nb@example.com")
        log = NotificationLog(
            user=user,
            event_type="nonsense",
            channel=NotificationLog.Channel.PUSH,
        )
        with pytest.raises(ValidationError):
            log.full_clean()