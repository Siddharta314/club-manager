"""Shared pytest fixtures for the clubs app."""
import pytest


@pytest.fixture
def club_factory(db):
    from model_bakery import baker

    def make(**kwargs):
        return baker.make("clubs.Club", **kwargs)

    return make