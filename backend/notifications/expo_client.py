"""Thin Expo Push client.

A minimal stdlib-based wrapper for the Expo Push HTTP API
(``https://exp.host/--/api/v2/push/send``). We keep our own
implementation rather than depending on a third-party SDK because:

1. The surface we need is tiny — one ``POST`` to a JSON endpoint.
2. Tests mock this module, so the actual HTTP call only matters in
   production. Pulling in an external SDK would add weight and a
   version constraint we don't need.
3. The Expo Push API is documented and stable; future SDK changes
   would still fit the same shape.

If the project grows to need richer Expo Push features
(scheduled delivery, rich content, etc.) swap this module for the
official ``expo-server-sdk`` Python package — the call site
(``notifications.tasks.send_notification``) only depends on the
public names exported here (``ExpoPushMessage``, ``ExpoPushTicket``,
``send_expo_push_notifications``).
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any


logger = logging.getLogger(__name__)


EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


@dataclass
class ExpoPushMessage:
    """A single push message addressed to an Expo push token."""

    to: str
    title: str
    body: str
    data: dict[str, Any] = field(default_factory=dict)
    sound: str | None = "default"


@dataclass
class ExpoPushTicket:
    """Result for a single push attempt.

    Mirrors the shape of one ticket in the Expo Push API response
    (per-message in the array):

    - ``status`` — ``"ok"`` on success, ``"error"`` on failure.
    - ``message`` — human-readable error message on failure.
    - ``ticket_id`` — Expo's ticket id on success (used for
      receipt polling, which we don't currently do).
    """

    status: str
    message: str | None = None
    ticket_id: str | None = None

    @classmethod
    def from_response(cls, payload: dict[str, Any]) -> ExpoPushTicket:
        """Build a ticket from a single Expo response payload."""
        if payload.get("status") == "ok":
            return cls(status="ok", ticket_id=payload.get("id"))
        details = payload.get("details") or {}
        err = details.get("error") or payload.get("message") or "unknown"
        return cls(status="error", message=str(err))


def send_expo_push_notifications(
    messages: list[ExpoPushMessage],
) -> list[ExpoPushTicket]:
    """POST a batch of push messages to Expo and return per-message tickets.

    Any network / decode error short-circuits the whole batch with a
    list of ``status="error"`` tickets — the caller treats them as
    failures and logs accordingly.
    """
    if not messages:
        return []
    body = json.dumps([asdict(m) for m in messages]).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Accept-encoding": "gzip, deflate",
    }
    access_token = os.environ.get("EXPO_ACCESS_TOKEN")
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    request = urllib.request.Request(
        EXPO_PUSH_URL, data=body, headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        logger.warning("Expo Push call failed: %s", exc)
        return [ExpoPushTicket(status="error", message=str(exc)) for _ in messages]
    except json.JSONDecodeError as exc:
        logger.warning("Expo Push returned non-JSON: %s", exc)
        return [ExpoPushTicket(status="error", message=f"invalid JSON: {exc}") for _ in messages]

    tickets_raw = data.get("data") or []
    if not isinstance(tickets_raw, list):
        # Whole-request error shape (e.g., an auth problem).
        message = data.get("message") or "unknown"
        return [ExpoPushTicket(status="error", message=str(message)) for _ in messages]

    out: list[ExpoPushTicket] = []
    for entry in tickets_raw:
        if not isinstance(entry, dict):
            out.append(ExpoPushTicket(status="error", message="non-dict ticket"))
            continue
        out.append(ExpoPushTicket.from_response(entry))
    return out