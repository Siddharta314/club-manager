"""Tests for the notifications app — Q2 task ``send_notification``.

Covers the per-user dispatch logic:

- Push: respects ``notify_push`` flag and ``push_token`` presence.
  Sends via the mocked ``expo_client.send_expo_push_notifications``;
  logs the result to ``NotificationLog``.
- Email: respects ``notify_email`` flag and email presence. Sends
  via Django's ``send_mail`` (mocked); logs the result.
- User-not-found path: returns skipped for both channels with an
  error string.
- Failure paths: push ticket with ``status="error"`` → push failed,
  email exception → email failed. Both write NotificationLog rows
  with status ``FAILED`` and a captured error message.
- Combined dispatch: when both push and email are opted in, the
  function writes two NotificationLog rows (one per channel).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from django.core import mail

from notifications.expo_client import ExpoPushTicket
from notifications.models import NotificationLog
from notifications.tasks import send_notification
from players.models import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_user(**overrides) -> User:
    """Create a user with sensible defaults for notification testing."""
    defaults = {
        "username": "nt_user",
        "email": "nt@example.com",
        "notify_push": True,
        "notify_email": True,
        "push_token": "ExponentPushToken[fake-token]",
    }
    defaults.update(overrides)
    return User.objects.create(**defaults)


# ---------------------------------------------------------------------------
# User-not-found path
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSendNotificationUserNotFound:
    def test_missing_user_returns_skipped_with_error(self) -> None:
        result = send_notification(user_id=999_999, event_type="match_created", payload={})
        assert result["push"] == "skipped"
        assert result["email"] == "skipped"
        assert any("not found" in e.lower() for e in result["errors"])


# ---------------------------------------------------------------------------
# Push channel
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSendNotificationPush:
    @patch("notifications.tasks.send_expo_push_notifications")
    def test_push_sent_logs_notification_log_sent(
        self, mock_send_push: MagicMock
    ) -> None:
        user = _make_user(notify_email=False)
        mock_send_push.return_value = [ExpoPushTicket(status="ok", ticket_id="t-1")]

        result = send_notification(
            user_id=user.pk, event_type="match_created", payload={"court_name": "C1"}
        )
        assert result["push"] == "sent"
        # NotificationLog: push only (email suppressed via notify_email=False).
        logs = NotificationLog.objects.filter(user=user)
        assert logs.count() == 1
        log = logs.first()
        assert log.channel == NotificationLog.Channel.PUSH
        assert log.status == NotificationLog.Status.SENT
        assert log.event_type == NotificationLog.EventType.MATCH_CREATED

    @patch("notifications.tasks.send_expo_push_notifications")
    def test_push_skipped_when_notify_push_false(
        self, mock_send_push: MagicMock
    ) -> None:
        user = _make_user(notify_push=False)
        result = send_notification(user_id=user.pk, event_type="match_created", payload={})
        assert result["push"] == "skipped"
        # No push client call — opt-out is a silent skip.
        mock_send_push.assert_not_called()

    @patch("notifications.tasks.send_expo_push_notifications")
    def test_push_skipped_when_no_push_token(
        self, mock_send_push: MagicMock
    ) -> None:
        user = _make_user(push_token="")
        result = send_notification(user_id=user.pk, event_type="match_created", payload={})
        assert result["push"] == "skipped"
        mock_send_push.assert_not_called()
        log = NotificationLog.objects.get(
            user=user, channel=NotificationLog.Channel.PUSH
        )
        assert log.status == NotificationLog.Status.SKIPPED
        assert "no push_token" in log.error

    @patch("notifications.tasks.send_expo_push_notifications")
    def test_push_failed_logs_status_failed(
        self, mock_send_push: MagicMock
    ) -> None:
        user = _make_user()
        mock_send_push.return_value = [
            ExpoPushTicket(status="error", message="DeviceNotRegistered")
        ]
        result = send_notification(user_id=user.pk, event_type="match_created", payload={})
        assert result["push"] == "failed"
        assert any("DeviceNotRegistered" in e for e in result["errors"])
        log = NotificationLog.objects.get(
            user=user, channel=NotificationLog.Channel.PUSH
        )
        assert log.status == NotificationLog.Status.FAILED
        assert "DeviceNotRegistered" in log.error

    @patch("notifications.tasks.send_expo_push_notifications")
    def test_push_exception_in_call_logs_failed(
        self, mock_send_push: MagicMock
    ) -> None:
        user = _make_user()
        mock_send_push.side_effect = RuntimeError("network down")
        result = send_notification(user_id=user.pk, event_type="match_created", payload={})
        assert result["push"] == "failed"
        log = NotificationLog.objects.get(
            user=user, channel=NotificationLog.Channel.PUSH
        )
        assert log.status == NotificationLog.Status.FAILED
        assert "network down" in log.error


# ---------------------------------------------------------------------------
# Email channel
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSendNotificationEmail:
    @patch("notifications.tasks.send_expo_push_notifications")
    def test_email_sent_logs_notification_log_sent(
        self, mock_send_push: MagicMock
    ) -> None:
        mock_send_push.return_value = []  # No push ticket.
        user = _make_user()
        result = send_notification(
            user_id=user.pk, event_type="player_joined", payload={"joining_user_name": "Alex"}
        )
        assert result["email"] == "sent"
        # Exactly one email went through Django's mail backend.
        assert len(mail.outbox) == 1
        assert "Alex" in mail.outbox[0].body
        log = NotificationLog.objects.get(
            user=user, channel=NotificationLog.Channel.EMAIL
        )
        assert log.status == NotificationLog.Status.SENT
        assert log.event_type == NotificationLog.EventType.MATCH_JOINED

    @patch("notifications.tasks.send_expo_push_notifications")
    def test_email_skipped_when_notify_email_false(
        self, mock_send_push: MagicMock
    ) -> None:
        mock_send_push.return_value = []
        user = _make_user(notify_email=False)
        result = send_notification(user_id=user.pk, event_type="match_created", payload={})
        assert result["email"] == "skipped"
        assert len(mail.outbox) == 0
        # No email NotificationLog row at all (we only log on actual
        # decision branches: opt-in + no token = skip logged; opt-out
        # = no email log).
        assert not NotificationLog.objects.filter(
            user=user, channel=NotificationLog.Channel.EMAIL
        ).exists()

    @patch("notifications.tasks.send_expo_push_notifications")
    def test_email_skipped_when_no_email(
        self, mock_send_push: MagicMock
    ) -> None:
        mock_send_push.return_value = []
        user = _make_user(email="")
        result = send_notification(user_id=user.pk, event_type="match_created", payload={})
        assert result["email"] == "skipped"
        log = NotificationLog.objects.get(
            user=user, channel=NotificationLog.Channel.EMAIL
        )
        assert log.status == NotificationLog.Status.SKIPPED
        assert "no email" in log.error

    @patch("notifications.tasks.send_expo_push_notifications")
    def test_email_failed_logs_status_failed(
        self, mock_send_push: MagicMock
    ) -> None:
        mock_send_push.return_value = []
        user = _make_user()
        # Patch the send_mail symbol imported into tasks.py.
        with patch("notifications.tasks.send_mail") as mock_send_mail:
            mock_send_mail.side_effect = RuntimeError("smtp down")
            result = send_notification(
                user_id=user.pk, event_type="match_created", payload={}
            )
        assert result["email"] == "failed"
        assert any("smtp down" in e for e in result["errors"])
        log = NotificationLog.objects.get(
            user=user, channel=NotificationLog.Channel.EMAIL
        )
        assert log.status == NotificationLog.Status.FAILED


# ---------------------------------------------------------------------------
# Combined dispatch
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSendNotificationBothChannels:
    @patch("notifications.tasks.send_expo_push_notifications")
    def test_both_push_and_email_succeed_writes_two_logs(
        self, mock_send_push: MagicMock
    ) -> None:
        mock_send_push.return_value = [ExpoPushTicket(status="ok", ticket_id="t-2")]
        user = _make_user()
        result = send_notification(
            user_id=user.pk, event_type="match_created", payload={"court_name": "C"}
        )
        assert result["push"] == "sent"
        assert result["email"] == "sent"
        assert NotificationLog.objects.filter(user=user).count() == 2
        channels = set(
            NotificationLog.objects.filter(user=user).values_list("channel", flat=True)
        )
        assert channels == {NotificationLog.Channel.PUSH, NotificationLog.Channel.EMAIL}

    @patch("notifications.tasks.send_expo_push_notifications")
    def test_both_channels_disabled_writes_no_logs(
        self, mock_send_push: MagicMock
    ) -> None:
        mock_send_push.return_value = []
        user = _make_user(notify_push=False, notify_email=False)
        result = send_notification(user_id=user.pk, event_type="match_created", payload={})
        assert result["push"] == "skipped"
        assert result["email"] == "skipped"
        assert NotificationLog.objects.filter(user=user).count() == 0
        mock_send_push.assert_not_called()


# ---------------------------------------------------------------------------
# Event-type body rendering
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestEventBody:
    @patch("notifications.tasks.send_expo_push_notifications")
    def test_match_created_body_uses_court_name(
        self, mock_send_push: MagicMock
    ) -> None:
        mock_send_push.return_value = []
        user = _make_user()
        send_notification(
            user_id=user.pk,
            event_type="match_created",
            payload={"court_name": "Court 5"},
        )
        assert "Court 5" in mail.outbox[0].body

    @patch("notifications.tasks.send_expo_push_notifications")
    def test_player_left_body_uses_name(
        self, mock_send_push: MagicMock
    ) -> None:
        mock_send_push.return_value = []
        user = _make_user()
        send_notification(
            user_id=user.pk,
            event_type="player_left",
            payload={"leaving_user_name": "Beatriz"},
        )
        assert "Beatriz" in mail.outbox[0].body