"""``is_queryset`` - what the queryset-shaping fields may be applied to."""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from django.db.models.manager import BaseManager


def is_queryset(obj: Any) -> bool:
    """True for Django ``QuerySet`` objects and ``Manager`` instances.

    The one definition of a queryset-shaping target: what the shaping fields
    may be applied to, what a RETRIEVE selector materializes from, and what
    ``paginate_output`` pages by counting. Tested by type rather than by
    ``hasattr(…, "first")``, which would also match a domain object that
    happens to expose ``first``. ``QuerySet`` subclasses all pass, and every
    ``BaseManager``, so one built with ``BaseManager.from_queryset`` does too.
    """
    return isinstance(obj, (QuerySet, BaseManager))
