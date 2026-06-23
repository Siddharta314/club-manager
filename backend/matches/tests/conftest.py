"""Shared pytest fixtures for the matches app."""
from datetime import timedelta

import pytest
from django.utils import timezone


@pytest.fixture
def match_factory(db):
    from model_bakery import baker

    def make(**kwargs):
        return baker.make("matches.Match", **kwargs)

    return make


@pytest.fixture
def match_player_factory(db):
    from model_bakery import baker

    def make(**kwargs):
        return baker.make("matches.MatchPlayer", **kwargs)

    return make


@pytest.fixture
def club_with_matches(db):
    """Build: 1 Club + 1 Court + 3 Matches (1 open + 1 cancelled + 1 full).

    Returns ``(club, court, open_match, cancelled_match, full_match)``.

    Used by ``TestMatchListView`` per REQ-MATCH-008(c) — the spec's
    "only open matches" test requires a data point where the
    ``total__lt=4`` filter is meaningful (the full match) and the
    ``is_cancelled=False`` filter is also exercised (the cancelled
    match). The open match is the only one the endpoint MUST return.

    Match counts:
    - ``open_match``: host only, 1 MatchPlayer, ``is_cancelled=False``.
    - ``cancelled_match``: host only, 1 MatchPlayer, ``is_cancelled=True``.
    - ``full_match``: host + 3 joined players, 4 MatchPlayers,
      ``is_cancelled=False``.
    """
    from clubs.models import Club, Court
    from match_slots.models import MatchSlot
    from matches.services import create_match_from_slot, join_match
    from players.models import User

    creator = User.objects.create(
        username="m_cwm_creator", email="m_cwm_creator@example.com"
    )
    club = Club.objects.create(name="LMC", address="LMC 1", created_by=creator)
    court = Court.objects.create(club=club, name="LMC Court")

    def _slot(offset_minutes: int) -> MatchSlot:
        start = timezone.now() + timedelta(minutes=offset_minutes)
        return MatchSlot.objects.create(
            court=court,
            start_time=start,
            end_time=start + timedelta(minutes=90),
        )

    # 1) Open match — host only.
    host_open = User.objects.create(
        username="m_cwm_oh", email="m_cwm_oh@example.com", level=3.50
    )
    open_match = create_match_from_slot(slot=_slot(60), host=host_open)

    # 2) Cancelled match — host only, then flag.
    host_cancelled = User.objects.create(
        username="m_cwm_ch", email="m_cwm_ch@example.com", level=3.50
    )
    cancelled_match = create_match_from_slot(
        slot=_slot(180), host=host_cancelled
    )
    cancelled_match.is_cancelled = True
    cancelled_match.save(update_fields=["is_cancelled"])

    # 3) Full match — host + 3 joined players (force=True skips level check).
    host_full = User.objects.create(
        username="m_cwm_fh", email="m_cwm_fh@example.com", level=3.50
    )
    full_match = create_match_from_slot(slot=_slot(300), host=host_full)
    for i in range(3):
        joined = User.objects.create(
            username=f"m_cwm_fp{i}",
            email=f"m_cwm_fp{i}@example.com",
            level=3.50,
        )
        join_match(match=full_match, user=joined, force=True)

    return club, court, open_match, cancelled_match, full_match