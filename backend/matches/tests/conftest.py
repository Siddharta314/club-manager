"""Shared pytest fixtures for the matches app."""
import pytest


@pytest.fixture
def match_factory(db):
    from model_bakery import baker

    def make(**kwargs):
        return baker.make("matches.Match", **kwargs)

    return make


@pytest.fixture
def match_player_factory(db):
    from model_bakery import baker

    def make(**kwargs):
        return baker.make("matches.MatchPlayer", **kwargs)

    return make