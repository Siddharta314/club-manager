"""Shared pytest fixtures for the match_slots app."""
import pytest


@pytest.fixture
def court_factory(db):
    from model_bakery import baker

    def make(**kwargs):
        return baker.make("clubs.Court", **kwargs)

    return make


@pytest.fixture
def match_slot_factory(db):
    from model_bakery import baker

    def make(**kwargs):
        return baker.make("match_slots.MatchSlot", **kwargs)

    return make