"""Tests for the companions app — Companion model.

Covers creation, level validation, sponsor relationship, and cascade
delete with the parent match.
"""
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from clubs.models import Club, Court
from companions.models import Companion
from match_slots.models import MatchSlot
from matches.models import Match, MatchPlayer
from players.models import User


def _court(db):
    creator = User.objects.create(username="co_creator", email="co@example.com")
    club = Club.objects.create(name="CO", address="CO 1", created_by=creator)
    return Court.objects.create(club=club, name="CO Court")


def _match_with_host(db):
    court = _court(None)
    host = User.objects.create(username="co_host", email="ch@example.com")
    start = timezone.now() + timedelta(days=1)
    slot = MatchSlot.objects.create(
        court=court, start_time=start, end_time=start + timedelta(hours=1)
    )
    match = Match.objects.create(host=host)
    slot.booked_match = match
    slot.save()
    MatchPlayer.objects.create(match=match, user=host)
    return match, host


@pytest.mark.django_db
class TestCompanion:
    def test_create_companion(self):
        match, host = _match_with_host(None)
        c = Companion.objects.create(
            match=match, sponsored_by=host, name="Alex", level=3.40
        )
        assert c.name == "Alex"
        assert c.level == 3.40
        assert c.sponsored_by == host
        assert c.created_at is not None

    def test_companion_level_must_be_in_range(self):
        match, host = _match_with_host(None)
        c = Companion(match=match, sponsored_by=host, name="Bad", level=8.50)
        with pytest.raises(ValidationError):
            c.full_clean()

    def test_companion_level_below_minimum_rejected(self):
        match, host = _match_with_host(None)
        c = Companion(match=match, sponsored_by=host, name="Bad", level=-1.00)
        with pytest.raises(ValidationError):
            c.full_clean()

    def test_companion_cascade_deletes_with_match(self):
        match, host = _match_with_host(None)
        Companion.objects.create(
            match=match, sponsored_by=host, name="Cas", level=3.0
        )
        match_id = match.id
        match.delete()
        assert not Companion.objects.filter(match_id=match_id).exists()

    def test_match_participant_count_includes_companions(self):
        match, host = _match_with_host(None)
        for i in range(3):
            Companion.objects.create(
                match=match, sponsored_by=host, name=f"G{i}", level=3.0
            )
        assert match.participant_count() == 4  # 1 player + 3 companions
        assert match.is_full is True


@pytest.mark.django_db
class TestCompanionRelations:
    def test_match_reverse_relation_lists_companions(self):
        match, host = _match_with_host(None)
        c1 = Companion.objects.create(
            match=match, sponsored_by=host, name="C1", level=3.0
        )
        c2 = Companion.objects.create(
            match=match, sponsored_by=host, name="C2", level=3.5
        )
        assert list(match.companions.order_by("created_at")) == [c1, c2]

    def test_sponsor_reverse_relation(self):
        match, host = _match_with_host(None)
        c = Companion.objects.create(
            match=match, sponsored_by=host, name="Sponsored", level=3.0
        )
        assert c in host.companions_sponsored.all()