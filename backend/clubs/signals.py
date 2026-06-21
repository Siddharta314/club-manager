"""clubs app — signals.

A single signal handler today: when a ``Schedule`` is saved, schedule
slot generation to run ``on_commit`` so the slot rows are visible only
after the surrounding transaction commits.

Why ``on_commit``:
- Avoids generating slots for a transaction that ends up rolling back.
- Prevents the view from blocking on slot creation.
- Keeps the operation transactional via ``generate_slots``'s own
  ``transaction.atomic`` block.
"""
from __future__ import annotations

from typing import Any

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Schedule
from .services import generate_slots


@receiver(post_save, sender=Schedule)
def schedule_post_save(
    sender: type[Schedule],
    instance: Schedule,
    created: bool,
    **kwargs: Any,
) -> None:
    """Trigger slot generation after Schedule save.

    The handler is intentionally fire-and-forget — slot generation is
    idempotent for the same schedule inputs so duplicate invocations
    during a multi-step update are safe.
    """
    transaction.on_commit(lambda: generate_slots(instance))
