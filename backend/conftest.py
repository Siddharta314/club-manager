"""Top-level pytest configuration.

Pulls in `pytest-django` configuration from `pytest.ini`, exposes shared
fixtures (see per-app `tests/conftest.py` for app-specific helpers), and
configures coverage.
"""
import pytest


@pytest.fixture
def user_factory(db):
    """Lazy user factory using model_bakery.

    Yields a callable that accepts kwargs and returns a persisted User. Uses
    `model_bakery` rather than `factory-boy` to avoid having to declare a
    Factory class for every model — every test gets a fresh DB thanks to the
    `db` fixture.
    """
    from model_bakery import baker

    def make(**kwargs):
        return baker.make("players.User", **kwargs)

    return make