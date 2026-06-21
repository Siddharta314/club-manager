"""clubs app — service layer.

Business rules live here, away from views so they're testable in
isolation. Currently hosts:

- ``generate_slots(schedule)`` — the eager slot generation routine
  invoked by the ``Schedule`` ``post_save`` signal.

The slot-generation algorithm is the central design decision for the
match-slots capability. It must be:

- **Transactional** — partial state (some new slots, some old) is
  unacceptable.
- **Idempotent for the same schedule inputs** — re-saving a Schedule
  with the same window produces the same slot set.
- **Past-preserving** — already-past slots are left alone (they may
  have historical matches attached).
- **Safe with booked slots** — slots with a ``booked_match`` are
  preserved even when future; only empty future slots are replaced.
"""
from __future__ import annotations

import datetime
import logging
from typing import Any

from django.db import transaction
from django.utils import timezone

from match_slots.models import MatchSlot

from .models import Schedule

logger = logging.getLogger(__name__)


def generate_slots(schedule: Schedule) -> list[MatchSlot]:
    """Generate empty ``MatchSlot`` rows for ``schedule``.

    Steps (run inside a transaction):

    1. Delete future, unbooked slots for the schedule's court. Booked
       slots and past slots are preserved.
    2. Walk ``schedule.start_time`` → ``schedule.end_time`` in steps of
       ``schedule.duration_minutes`` over the next 28 days (a four-week
       horizon — long enough for the mobile client, short enough to
       avoid bloating the table).
    3. ``bulk_create`` the new slots.

    Returns the list of new slot instances (pre-``bulk_create`` refresh,
    so PKs may be unset on SQLite if it allocated them in bulk; callers
    that need PKs should refetch).
    """
    from match_slots.models import MatchSlot as _MatchSlot  # local for typing

    court = schedule.court
    horizon_days: int = 28

    today = timezone.localdate()
    new_slots: list[_MatchSlot] = []

    for offset in range(horizon_days):
        target_date = today + datetime.timedelta(days=offset)
        if target_date.weekday() != schedule.weekday:
            continue
        # Combine the rule's start_time / end_time with the date and
        # make the resulting datetimes timezone-aware.
        tz = timezone.get_current_timezone()
        slot_start = timezone.make_aware(
            datetime.datetime.combine(target_date, schedule.start_time),
            tz,
        )
        day_end = timezone.make_aware(
            datetime.datetime.combine(target_date, schedule.end_time),
            tz,
        )
        step = datetime.timedelta(minutes=schedule.duration_minutes)
        cursor = slot_start
        while cursor + step <= day_end:
            new_slots.append(
                _MatchSlot(
                    court=court,
                    start_time=cursor,
                    end_time=cursor + step,
                    is_active=True,
                )
            )
            cursor = cursor + step

    with transaction.atomic():
        # Delete future, unbooked slots for this court only. Past slots
        # stay so historical matches are intact. Booked future slots
        # stay so an in-progress match isn't wiped by an admin editing
        # the schedule window.
        MatchSlot.objects.filter(
            court=court,
            start_time__gt=timezone.now(),
            booked_match__isnull=True,
        ).delete()
        if new_slots:
            created = MatchSlot.objects.bulk_create(new_slots)
            logger.info(
                "generate_slots schedule_id=%s court_id=%s created=%s horizon=%sd",
                schedule.id,
                court.id,
                len(created),
                horizon_days,
            )
            return list(created)
    return []
