"""Tests for the matches app — Match and MatchPlayer.

Covers the level-range invariant, derived lifecycle properties, and the
MatchPlayer uniqueness + host computation.
"""
from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from clubs.models import Club, Court
from match_slots.models import MatchSlot
from matches.models import Match, MatchPlayer
from players.models import User


def _court(db):
    creator = User.objects.create(username="mc_creator", email="mc@example.com")
    club = Club.objects.create(name="MC", address="M 1", created_by=creator)
    return Court.objects.create(club=club, name="MC Court")


def _future_slot(court):
    start = timezone.now() + timedelta(days=1)
    return MatchSlot.objects.create(
        court=court, start_time=start, end_time=start + timedelta(minutes=90)
    )


@pytest.mark.django_db
class TestMatch:
    def test_create_match_with_slot_and_host(self):
        court = _court(None)
        host = User.objects.create(username="host", email="h@example.com")
        slot = _future_slot(court)
        match = Match.objects.create(host=host)
        slot.booked_match = match
        slot.save()
        assert match.is_cancelled is False
        assert match.host == host
        assert match.slot == slot

    def test_level_range_must_be_valid(self):
        court = _court(None)
        host = User.objects.create(username="h2", email="h2@example.com")
        _future_slot(court)
        with pytest.raises(IntegrityError), transaction.atomic():
            Match.objects.create(
                host=host,
                level_min=4.00,
                level_max=3.00,  # max < min → invariant violation
            )

    def test_default_level_range_is_open_enough_for_default_player(self):
        court = _court(None)
        host = User.objects.create(username="h3", email="h3@example.com")
        slot = _future_slot(court)
        match = Match.objects.create(host=host)
        slot.booked_match = match
        slot.save()
        assert match.level_min <= host.level <= match.level_max

    def test_is_open_defaults_to_true(self):
        court = _court(None)
        host = User.objects.create(username="h4", email="h4@example.com")
        slot = _future_slot(court)
        match = Match.objects.create(host=host)
        slot.booked_match = match
        slot.save()
        assert match.is_open is True
        match.is_cancelled = True
        assert match.is_open is False

    def test_is_full_counts_players_and_companions(self):
        """The 4-cap rule is verified end-to-end in the companions PR (commit 9)
        once the Companion model and reverse relation ship together."""
        court = _court(None)
        host = User.objects.create(username="h5", email="h5@example.com")
        slot = _future_slot(court)
        match = Match.objects.create(host=host)
        slot.booked_match = match
        slot.save()
        MatchPlayer.objects.create(match=match, user=host)
        # Match.participant_count() returns 1 (the host) — Companion model
        # is added in commit 9 and the count grows to 4 with 3 companions.
        assert match.participant_count() == 1
        assert match.is_full is False


@pytest.mark.django_db
class TestMatchLifecycleProperties:
    def _make_match_with_slot(self, start_offset_minutes):
        court = _court(None)
        host = User.objects.create(username=f"host_{start_offset_minutes}", email="x@x.com")
        start = timezone.now() + timedelta(minutes=start_offset_minutes)
        slot = MatchSlot.objects.create(
            court=court, start_time=start, end_time=start + timedelta(minutes=90)
        )
        match = Match.objects.create(host=host)
        slot.booked_match = match
        slot.save()
        return match

    def test_is_in_progress_when_now_between_start_and_end(self):
        # -30 minutes (already started), ends +60 minutes from now.
        match = self._make_match_with_slot(-30)
        assert match.is_in_progress is True
        assert match.is_finished is False

    def test_is_finished_after_end_time(self):
        # Slot that ended an hour ago — adjust start/end to be in the past.
        court = _court(None)
        host = User.objects.create(username="past_host", email="p@p.com")
        start = timezone.now() - timedelta(hours=2)
        slot = MatchSlot.objects.create(
            court=court,
            start_time=start,
            end_time=start + timedelta(minutes=60),
        )
        match = Match.objects.create(host=host)
        slot.booked_match = match
        slot.save()
        assert match.is_finished is True
        assert match.is_in_progress is False

    def test_is_not_in_progress_when_cancelled(self):
        match = self._make_match_with_slot(-30)
        match.is_cancelled = True
        assert match.is_in_progress is False


@pytest.mark.django_db
class TestMatchPlayer:
    def test_host_is_first_player(self):
        court = _court(None)
        host = User.objects.create(username="hp", email="hp@example.com")
        slot = _future_slot(court)
        match = Match.objects.create(host=host)
        slot.booked_match = match
        slot.save()
        mp = MatchPlayer.objects.create(match=match, user=host)
        assert mp.is_host is True

    def test_non_host_player(self):
        court = _court(None)
        host = User.objects.create(username="hp1", email="hp1@example.com")
        player = User.objects.create(username="pl1", email="pl1@example.com")
        slot = _future_slot(court)
        match = Match.objects.create(host=host)
        slot.booked_match = match
        slot.save()
        MatchPlayer.objects.create(match=match, user=host)
        mp_player = MatchPlayer.objects.create(match=match, user=player)
        assert mp_player.is_host is False

    def test_unique_player_per_match(self):
        court = _court(None)
        host = User.objects.create(username="hu", email="hu@example.com")
        slot = _future_slot(court)
        match = Match.objects.create(host=host)
        slot.booked_match = match
        slot.save()
        MatchPlayer.objects.create(match=match, user=host)
        with pytest.raises(IntegrityError), transaction.atomic():
            MatchPlayer.objects.create(match=match, user=host)