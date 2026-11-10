from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from django.db.models.manager import BaseManager


def is_queryset(obj: Any) -> bool:
    """True for Django ``QuerySet`` objects and ``Manager`` instances."""
    return isinstance(obj, (QuerySet, BaseManager))
