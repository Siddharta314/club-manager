"""Shared pytest fixtures for the players app."""
import pytest


@pytest.fixture
def player_factory(db):
    from model_bakery import baker

    def make(**kwargs):
        return baker.make("players.User", **kwargs)

    return make