"""Tests for the companions app — service layer.

Covers the business rules in ``companions.services``:

- ``register_companion`` — sponsor gate, capacity check, cascade.
- ``remove_companion`` — delete behaviour.
- Cascade-delete with Match (covered indirectly via remove).
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from clubs.models import Club, Court
from companions.models import Companion
from companions.services import register_companion, remove_companion
from match_slots.models import MatchSlot
from matches.models import Match, MatchPlayer
from matches.services import create_match_from_slot, join_match
from players.models import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_match_with_host(host_level: float = 3.50):
    """Create a Match with the host signed up. Returns (match, host)."""
    creator = User.objects.create(
        username="cs_creator", email="cs_creator@example.com"
    )
    club = Club.objects.create(name="CS", address="CS 1", created_by=creator)
    court = Court.objects.create(club=club, name="CS Court")
    start = timezone.now() + timedelta(hours=1)
    slot = MatchSlot.objects.create(
        court=court,
        start_time=start,
        end_time=start + timedelta(minutes=90),
    )
    host = User.objects.create(
        username="cs_host", email="cs_host@example.com", level=host_level
    )
    match = create_match_from_slot(slot=slot, host=host)
    return match, host


# ---------------------------------------------------------------------------
# register_companion
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRegisterCompanion:
    def test_creates_companion_tied_to_sponsor(self) -> None:
        match, host = _make_match_with_host()
        c = register_companion(match=match, sponsor=host, name="Alex", level=3.40)
        assert c.name == "Alex"
        assert c.level == 3.40
        assert c.sponsored_by == host
        assert c.match == match

    def test_rejects_non_player_sponsor(self) -> None:
        match, _ = _make_match_with_host()
        # A user that's NOT a MatchPlayer on the match.
        outsider = User.objects.create(
            username="out", email="out@example.com"
        )
        with pytest.raises(ValueError, match="not a player"):
            register_companion(
                match=match, sponsor=outsider, name="Bad", level=3.40
            )

    def test_rejects_full_match(self) -> None:
        match, host = _make_match_with_host(host_level=3.50)
        # Fill the match: 1 host + 3 players.
        for i in range(3):
            p = User.objects.create(
                username=f"p_{i}", email=f"p_{i}@example.com", level=3.50
            )
            join_match(match=match, user=p)
        assert match.is_full is True
        with pytest.raises(ValueError, match="full"):
            register_companion(
                match=match, sponsor=host, name="Late", level=3.40
            )

    def test_level_field_validates_0_to_7(self) -> None:
        match, host = _make_match_with_host()
        # Out-of-range level is rejected at the model level (LevelField
        # validators fire on ``full_clean``); the service passes the
        # value through to ``Companion.objects.create`` which skips
        # full_clean by default. We rely on the serializer layer
        # (covered in test_views.py) for the 400 response. The model
        # constraint test below pins the level cap so a future
        # refactor that adds a service-side check has a known target.
        c = Companion(match=match, sponsored_by=host, name="X", level=8.50)
        with pytest.raises(Exception):
            c.full_clean()

    def test_cascade_deletes_with_match(self) -> None:
        match, host = _make_match_with_host()
        c1 = register_companion(match=match, sponsor=host, name="C1", level=3.40)
        c2 = register_companion(match=match, sponsor=host, name="C2", level=3.50)
        match_id = match.id
        match.delete()
        assert not Companion.objects.filter(match_id=match_id).exists()
        # Sanity: the registered instances were real.
        assert c1.pk and c2.pk


# ---------------------------------------------------------------------------
# remove_companion
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRemoveCompanion:
    def test_deletes_companion(self) -> None:
        match, host = _make_match_with_host()
        c = register_companion(match=match, sponsor=host, name="Alex", level=3.40)
        pk = c.pk
        remove_companion(c)
        assert not Companion.objects.filter(pk=pk).exists()

    def test_removing_one_does_not_affect_others(self) -> None:
        match, host = _make_match_with_host()
        c1 = register_companion(
            match=match, sponsor=host, name="A", level=3.40
        )
        c2 = register_companion(
            match=match, sponsor=host, name="B", level=3.50
        )
        remove_companion(c1)
        assert not Companion.objects.filter(pk=c1.pk).exists()
        assert Companion.objects.filter(pk=c2.pk).exists()
