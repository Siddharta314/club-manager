"""Tests for the companions app — DRF serializers.

Covers the shared validator functions and the per-serializer hooks
that delegate to them. The validator functions live at module scope
in ``companions.serializers`` and are reused by both
``CompanionSerializer`` and ``CompanionCreateSerializer``; we test
them once directly so future refactors don't have to update
multiple test paths.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from rest_framework.exceptions import ValidationError

from companions.serializers import (
    CompanionCreateSerializer,
    CompanionSerializer,
    validate_companion_level,
    validate_companion_name,
)


# ---------------------------------------------------------------------------
# validate_companion_name
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Alex", "Alex"),
        ("  Alex  ", "Alex"),
        ("María", "María"),
    ],
)
def test_validate_companion_name_strips_and_accepts(raw: str, expected: str) -> None:
    assert validate_companion_name(raw) == expected


@pytest.mark.parametrize("bad", ["", "   ", "\t\n"])
def test_validate_companion_name_rejects_empty_or_whitespace(bad: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        validate_companion_name(bad)
    assert "empty" in str(exc_info.value).lower()


def test_validate_companion_name_rejects_none() -> None:
    with pytest.raises(ValidationError):
        validate_companion_name(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# validate_companion_level
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        (3.40, 3.40),
        (3, 3.0),
        (Decimal("3.50"), 3.50),
        ("4.25", 4.25),
        (0.00, 0.00),
        (7.00, 7.00),
    ],
)
def test_validate_companion_level_accepts_in_range(
    raw: float | int | str | Decimal, expected: float
) -> None:
    assert validate_companion_level(raw) == expected


@pytest.mark.parametrize("bad", [-0.01, 7.01, 10.00, -5.0])
def test_validate_companion_level_rejects_out_of_range(bad: float) -> None:
    with pytest.raises(ValidationError) as exc_info:
        validate_companion_level(bad)
    assert "between 0.00 and 7.00" in str(exc_info.value)


@pytest.mark.parametrize("bad", ["not-a-number", None, []])
def test_validate_companion_level_rejects_non_numeric(bad) -> None:
    with pytest.raises(ValidationError):
        validate_companion_level(bad)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Serializer integration — name and level hooks delegate to the helpers
# ---------------------------------------------------------------------------
def test_companion_serializer_validate_name_delegates_to_helper() -> None:
    """Whitespace-only name → ValidationError from the shared helper."""
    serializer = CompanionSerializer(data={"name": "   ", "level": 3.40})
    assert not serializer.is_valid()
    assert "name" in serializer.errors


def test_companion_serializer_validate_level_rejects_high() -> None:
    """Out-of-range level → 400.

    DRF's built-in Min/Max validators (derived from the ``LevelField``
    on the model) fire before our custom hook, so the message is the
    generic DRF one — but the request still returns 400 with the
    ``level`` field flagged. The custom helper is what catches
    non-numeric input (see ``test_companion_serializer_validate_level_rejects_non_numeric``).
    """
    serializer = CompanionSerializer(data={"name": "X", "level": 9.00})
    assert not serializer.is_valid()
    assert "level" in serializer.errors


def test_companion_serializer_validate_level_rejects_low() -> None:
    serializer = CompanionSerializer(data={"name": "X", "level": -1.00})
    assert not serializer.is_valid()
    assert "level" in serializer.errors


def test_companion_serializer_validate_level_rejects_non_numeric() -> None:
    """Non-numeric level → friendly 400 from our shared helper.

    DRF's Min/Max validators only fire on numeric inputs; for
    strings / lists / None our helper kicks in and returns the
    "Level must be a number" message.
    """
    serializer = CompanionSerializer(data={"name": "X", "level": "abc"})
    assert not serializer.is_valid()
    assert "level" in serializer.errors
    assert "number" in str(serializer.errors["level"]).lower()


def test_companion_create_serializer_validate_name_delegates_to_helper() -> None:
    serializer = CompanionCreateSerializer(data={"name": "", "level": 3.40})
    assert not serializer.is_valid()
    assert "name" in serializer.errors


def test_companion_create_serializer_validate_level_delegates_to_helper() -> None:
    """Create serializer shares the same level rule as the read one."""
    serializer = CompanionCreateSerializer(data={"name": "X", "level": 11.00})
    assert not serializer.is_valid()
    assert "level" in serializer.errors


def test_companion_create_serializer_validate_level_rejects_non_numeric() -> None:
    """Create serializer's level hook also funnels non-numeric → friendly 400."""
    serializer = CompanionCreateSerializer(data={"name": "X", "level": "abc"})
    assert not serializer.is_valid()
    assert "level" in serializer.errors
    assert "number" in str(serializer.errors["level"]).lower()