"""Notification dispatch service.

Enqueues per-user Q2 tasks for the three notification triggers the
spec calls out:

- ``enqueue_match_created(match_id)`` — fan-out to subscribed
  members of the club (excluding the host).
- ``enqueue_player_joined(match_id, joining_user_id)`` — fan-out to
  every other player on the match.
- ``enqueue_player_left(match_id, leaving_user_id)`` — same, on
  leave.

Each enqueue is a thin DB read + N ``send_notification.delay(...)``
calls. The actual push / email dispatch lives in
``notifications.tasks.send_notification``, which is what runs in
the Q2 worker process.

User opt-in checks (``User.notify_push``, ``User.notify_email``,
``User.push_token`` presence) happen **inside the task**, not here,
so enqueueing is a cheap read and the per-user decision is logged
via ``NotificationLog``.
"""
from __future__ import annotations

from typing import Any

from django.db.models import Q

from companions.models import Companion
from matches.models import Match, MatchPlayer
from players.models import User


def _match_other_user_ids(
    match: Match,
    exclude_user_id: int | None = None,
    *,
    include_host: bool = True,
) -> list[int]:
    """Return user IDs of MatchPlayers for the given match.

    ``exclude_user_id``: if set, drops that one user from the result.
    ``include_host``: if False, drops the host from the result.
    Both filters compose with AND. The default (``include_host=True``)
    preserves the historical "notify everyone except the excluded
    user" behavior of the player_joined / player_left helpers.
    """
    qs = MatchPlayer.objects.filter(match=match).values_list("user_id", flat=True)
    if not include_host:
        qs = qs.exclude(user_id=match.host_id)
    if exclude_user_id is not None:
        qs = qs.exclude(user_id=exclude_user_id)
    return list(qs)


def enqueue_match_created(match_id: int) -> None:
    """Notify subscribed players of the club that a new match was created.

    Scope: all users with ``User.club == this club`` and
    ``notify_push or notify_email = True``. The host is excluded so
    they don't get a "new match" notification about their own match.

    Each recipient is queued as an independent Q2 task so a slow
    push or email provider for one user doesn't block the rest.
    """
    match = Match.objects.select_related(
        "match_slot__court__club"
    ).get(pk=match_id)
    club = match.match_slot.court.club

    targets = (
        User.objects.filter(club=club)
        .exclude(pk=match.host_id)
        .filter(Q(notify_push=True) | Q(notify_email=True))
    )

    payload: dict[str, Any] = {
        "match_id": match.pk,
        "club_id": club.pk,
        "start_time": match.match_slot.start_time.isoformat(),
        "court_name": match.match_slot.court.name,
    }
    # Lazy import to keep this module importable without the Q2
    # task being on disk (so commit ordering stays clean: services
    # can land before tasks).
    from notifications.tasks import send_notification

    for user in targets:
        send_notification.delay(
            user_id=user.pk,
            event_type="match_created",
            payload=payload,
        )


def enqueue_player_joined(match_id: int, joining_user_id: int) -> None:
    """Notify the other players on the match that someone joined."""
    match = Match.objects.select_related(
        "match_slot__court__club"
    ).get(pk=match_id)
    other_user_ids = _match_other_user_ids(match, joining_user_id)
    joining_user = User.objects.get(pk=joining_user_id)
    payload: dict[str, Any] = {
        "match_id": match.pk,
        "joining_user_id": joining_user_id,
        "joining_user_name": (
            joining_user.get_full_name() or joining_user.email or ""
        ),
    }
    from notifications.tasks import send_notification

    for uid in other_user_ids:
        send_notification.delay(
            user_id=uid,
            event_type="player_joined",
            payload=payload,
        )


def enqueue_player_left(match_id: int, leaving_user_id: int) -> None:
    """Notify the remaining players on the match that someone left."""
    match = Match.objects.select_related(
        "match_slot__court__club"
    ).get(pk=match_id)
    other_user_ids = _match_other_user_ids(match, leaving_user_id)
    leaving_user = User.objects.get(pk=leaving_user_id)
    payload: dict[str, Any] = {
        "match_id": match.pk,
        "leaving_user_id": leaving_user_id,
        "leaving_user_name": (
            leaving_user.get_full_name() or leaving_user.email or ""
        ),
    }
    from notifications.tasks import send_notification

    for uid in other_user_ids:
        send_notification.delay(
            user_id=uid,
            event_type="player_left",
            payload=payload,
        )


def enqueue_match_cancelled(match_id: int) -> None:
    """Notify every MatchPlayer of the match (host included) that it was cancelled.

    Cancellation is the inverse of creation: the same players who
    would have been told the match exists need to know it doesn't
    anymore. Unlike ``enqueue_player_joined`` / ``enqueue_player_left``
    there is no "exclude the actor" — the cancellation was triggered
    by an admin or the host, who are NOT on the match's player
    notification path, so the host must be in the recipient set.

    Each recipient is queued as an independent Q2 task so a slow push
    or email provider for one user doesn't block the rest.
    """
    match = Match.objects.select_related(
        "match_slot__court__club"
    ).get(pk=match_id)
    user_ids = _match_other_user_ids(match, include_host=True)
    payload: dict[str, Any] = {
        "match_id": match.pk,
        "court_name": match.match_slot.court.name,
        "club_id": match.match_slot.court.club_id,
        "start_time": match.match_slot.start_time.isoformat(),
    }
    from notifications.tasks import send_notification

    for uid in user_ids:
        send_notification.delay(
            user_id=uid,
            event_type="match_cancelled",
            payload=payload,
        )