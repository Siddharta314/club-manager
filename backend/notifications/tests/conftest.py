"""Shared pytest fixtures for the notifications app."""
import pytest


@pytest.fixture
def notification_log_factory(db):
    from model_bakery import baker

    def make(**kwargs):
        return baker.make("notifications.NotificationLog", **kwargs)

    return make