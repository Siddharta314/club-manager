"""Custom model fields for the players app.

`LevelField` is the only custom field we need: padel levels are centesimal
decimals in the inclusive range [0.00, 7.00]. The field subclasses
`DecimalField` so it integrates naturally with Django validators, lookups,
and aggregation.

We pin the column signature (max_digits=4, decimal_places=2) so migrations
remain stable across the codebase.
"""
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db.models import DecimalField


class LevelField(DecimalField):
    """Centesimal padel level, 0.00–7.00, 2 decimal places.

    Usage::

        level = LevelField(default=Decimal("3.00"))

    Validation runs automatically on ``full_clean()`` and is also enforced by
    the database column check constraints added via migration. The range is
    intentionally hard-coded — level ceilings are part of the domain, not
    configuration.
    """

    MIN_LEVEL = Decimal("0.00")
    MAX_LEVEL = Decimal("7.00")

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_digits", 4)
        kwargs.setdefault("decimal_places", 2)
        kwargs.setdefault(
            "validators",
            [
                MinValueValidator(self.MIN_LEVEL),
                MaxValueValidator(self.MAX_LEVEL),
            ],
        )
        super().__init__(*args, **kwargs)