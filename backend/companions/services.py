"""Companion lifecycle business logic.

A Companion is an anonymous player attached to a specific Match.
Created by a signed-up MatchPlayer (the "sponsor"). Volatile: cascade-deleted with Match.
Capacity counts toward the 4-person total.
"""
from __future__ import annotations

from typing import Any

from .models import Companion


def register_companion(
    match: Any,
    sponsor: Any,
    name: str,
    level: float,
) -> Companion:
    """Register an anonymous companion on a match.

    Constraints:
    - Sponsor MUST be a MatchPlayer on this match (raise ValueError if not).
    - Match must not be full (raise ValueError if full).
    - Name non-empty (validated at serializer level too — defence in depth).
    - Level within valid range 0.00-7.00 (LevelField validators
      enforce this at the model level; we accept the value and let
      the serializer / model raise if it's malformed).

    Returns the created Companion.
    """
    # Local import to avoid an import cycle — matches.services imports
    # from companions lazily, so we mirror that pattern in reverse.
    from matches.models import MatchPlayer
    from matches.services import get_capacity_status

    if not MatchPlayer.objects.filter(match=match, user=sponsor).exists():
        raise ValueError(
            f"User {sponsor.pk} is not a player in match {match.pk}"
        )

    status = get_capacity_status(match)
    if status.is_full:
        raise ValueError("Match is full")

    return Companion.objects.create(
        match=match,
        sponsored_by=sponsor,
        name=name,
        level=level,
    )


def remove_companion(companion: Companion) -> None:
    """Delete a companion. Admin or sponsor only — caller must check permission.

    The function is intentionally permission-free so it can be called
    from any context (admin command, view, test). The view layer
    enforces the "sponsor or admin" gate before calling.
    """
    companion.delete()
