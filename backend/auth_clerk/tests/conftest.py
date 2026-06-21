"""Shared pytest fixtures for the auth_clerk app tests.

The cross-app ``make_clerk_state`` and ``bypass_clerk_auth`` fixtures
live in the top-level ``conftest.py`` so any test module can use them.
"""
from __future__ import annotations
