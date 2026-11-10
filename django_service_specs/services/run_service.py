from __future__ import annotations

from collections.abc import Callable
from typing import Any

from asgiref.sync import async_to_sync
from django.db import transaction

from django_service_specs.services.arun_service import arun_service
from django_service_specs.types.is_async import is_async


def run_service(
    fn: Callable[..., Any],
    kwargs: dict[str, Any],
    *,
    atomic: bool,
) -> Any:
    """Call ``fn(**kwargs)`` from sync code, optionally inside ``transaction.atomic()``."""
    if is_async(fn):
        return async_to_sync(arun_service)(fn, kwargs, atomic=atomic)
    if atomic:
        with transaction.atomic():
            return fn(**kwargs)
    return fn(**kwargs)
