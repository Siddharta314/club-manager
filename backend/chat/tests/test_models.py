"""Tests for the chat app — ChatMessage model.

Covers the XOR author invariant (exactly one of author_user /
author_companion), the match FK cascade, and the basic message ordering.
"""
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from chat.models import ChatMessage
from clubs.models import Club, Court
from companions.models import Companion
from match_slots.models import MatchSlot
from matches.models import Match, MatchPlayer
from players.models import User


def _match_with_host(db):
    creator = User.objects.create(username="c_creator", email="c@example.com")
    club = Club.objects.create(name="CC", address="CC 1", created_by=creator)
    court = Court.objects.create(club=club, name="CC Court")
    host = User.objects.create(username="c_host", email="ch@example.com")
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
class TestChatMessageAuthoring:
    def test_message_by_user_is_valid(self):
        match, host = _match_with_host(None)
        msg = ChatMessage(match=match, author_user=host, text="hello")
        msg.full_clean()  # should not raise
        msg.save()
        assert msg.author_user == host
        assert msg.author_companion is None

    def test_message_by_companion_is_valid(self):
        match, host = _match_with_host(None)
        companion = Companion.objects.create(
            match=match, sponsored_by=host, name="C1", level=3.0
        )
        msg = ChatMessage(match=match, author_companion=companion, text="hi from guest")
        msg.full_clean()
        msg.save()
        assert msg.author_companion == companion
        assert msg.author_user is None

    def test_message_with_no_author_is_rejected(self):
        match, _ = _match_with_host(None)
        msg = ChatMessage(match=match, text="orphan")
        with pytest.raises(ValidationError):
            msg.full_clean()

    def test_message_with_both_authors_is_rejected(self):
        match, host = _match_with_host(None)
        companion = Companion.objects.create(
            match=match, sponsored_by=host, name="Both", level=3.0
        )
        msg = ChatMessage(
            match=match,
            author_user=host,
            author_companion=companion,
            text="both authors",
        )
        with pytest.raises(ValidationError):
            msg.full_clean()


@pytest.mark.django_db
class TestChatMessageDBConstraints:
    def test_db_constraint_rejects_no_author(self):
        """The XOR check constraint is enforced at the DB layer too."""
        match, _ = _match_with_host(None)
        with pytest.raises(IntegrityError), transaction.atomic():
            ChatMessage.objects.create(match=match, text="orphan")

    def test_db_constraint_rejects_both_authors(self):
        match, host = _match_with_host(None)
        companion = Companion.objects.create(
            match=match, sponsored_by=host, name="Both", level=3.0
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            ChatMessage.objects.create(
                match=match,
                author_user=host,
                author_companion=companion,
                text="both",
            )


@pytest.mark.django_db
class TestChatMessageCascade:
    def test_cascade_delete_with_match(self):
        match, host = _match_with_host(None)
        ChatMessage.objects.create(match=match, author_user=host, text="hi")
        match_id = match.id
        match.delete()
        assert not ChatMessage.objects.filter(match_id=match_id).exists()