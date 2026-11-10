from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from asgiref.sync import async_to_sync, sync_to_async
from django.db import transaction


def _run_atomic_inner(
    fn: Callable[..., Awaitable[Any]],
    kwargs: dict[str, Any],
) -> Any:
    with transaction.atomic():
        return async_to_sync(fn)(**kwargs)


async def arun_service(
    fn: Callable[..., Awaitable[Any]],
    kwargs: dict[str, Any],
    *,
    atomic: bool,
) -> Any:
    """Await ``fn(**kwargs)``, optionally inside ``transaction.atomic()``."""
    if not atomic:
        return await fn(**kwargs)
    return await sync_to_async(_run_atomic_inner, thread_sensitive=True)(fn, kwargs)
