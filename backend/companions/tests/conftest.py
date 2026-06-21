"""Shared pytest fixtures for the companions app."""
import pytest


@pytest.fixture
def companion_factory(db):
    from model_bakery import baker

    def make(**kwargs):
        return baker.make("companions.Companion", **kwargs)

    return make