"""Shared pytest fixtures for the chat app."""
import pytest


@pytest.fixture
def chat_message_factory(db):
    from model_bakery import baker

    def make(**kwargs):
        return baker.make("chat.ChatMessage", **kwargs)

    return make