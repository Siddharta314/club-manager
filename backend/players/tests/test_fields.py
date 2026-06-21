"""Tests for `players.fields.LevelField`.

Covers the centesimal validation rules and the column-level invariants that
migrations rely on. Database round-trip checks for the `User.level` field
live in `test_models.py`.
"""
from decimal import Decimal

import pytest
from django.core import validators
from django.core.exceptions import ValidationError

from players.fields import LevelField


class TestLevelFieldConstruction:
    def test_pins_max_digits_and_decimal_places(self):
        field = LevelField()
        assert field.max_digits == 4
        assert field.decimal_places == 2

    def test_pins_validators_to_min_and_max(self):
        field = LevelField()
        validator_classes = [type(v) for v in field.validators]
        assert validators.MinValueValidator in validator_classes
        assert validators.MaxValueValidator in validator_classes

    def test_explicit_kwargs_override_defaults(self):
        field = LevelField(default=Decimal("4.25"))
        assert field.default == Decimal("4.25")

    def test_each_instance_keeps_exactly_one_min_and_max_validator(self):
        """Re-instantiation must not stack duplicate Min/Max validators."""
        LevelField()
        field = LevelField()
        validator_classes = [type(v) for v in field.validators]
        assert validator_classes.count(validators.MinValueValidator) == 1
        assert validator_classes.count(validators.MaxValueValidator) == 1

    def test_min_and_max_match_documented_constants(self):
        from players.fields import LevelField as L

        assert L.MIN_LEVEL == Decimal("0.00")
        assert L.MAX_LEVEL == Decimal("7.00")


class TestLevelFieldValidation:
    @pytest.fixture
    def field(self):
        return LevelField()

    @pytest.mark.parametrize(
        "value",
        [Decimal("0.00"), Decimal("3.00"), Decimal("3.12"), Decimal("4.25"), Decimal("7.00")],
    )
    def test_accepts_values_in_range(self, field, value):
        # Should not raise.
        field.run_validators(value)

    @pytest.mark.parametrize(
        "value",
        [Decimal("-0.01"), Decimal("-1.00"), Decimal("-3.50")],
    )
    def test_rejects_values_below_minimum(self, field, value):
        with pytest.raises(ValidationError):
            field.run_validators(value)

    @pytest.mark.parametrize(
        "value",
        [Decimal("7.01"), Decimal("8.00"), Decimal("99.99")],
    )
    def test_rejects_values_above_maximum(self, field, value):
        with pytest.raises(ValidationError):
            field.run_validators(value)

    def test_accepts_boundary_zero(self, field):
        field.run_validators(Decimal("0.00"))  # no raise

    def test_accepts_boundary_seven(self, field):
        field.run_validators(Decimal("7.00"))  # no raise


class TestLevelFieldSerialization:
    def test_deconstruct_signature_is_stable(self):
        """The deconstruct signature is what migrations use to recreate fields."""
        field = LevelField()
        name, path, args, kwargs = field.deconstruct()
        assert kwargs["max_digits"] == 4
        assert kwargs["decimal_places"] == 2
        assert any(isinstance(v, validators.MinValueValidator) for v in kwargs["validators"])
        assert any(isinstance(v, validators.MaxValueValidator) for v in kwargs["validators"])