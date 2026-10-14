"""``arun_selector`` - call a selector from a coroutine, whichever kind it is."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from django_service_specs.types.is_async import is_async


async def arun_selector(
    fn: Callable[..., Any] | Callable[..., Awaitable[Any]], kwargs: Mapping[str, Any]
) -> Any:
    """Call a selector from async code: an ``async def`` one is awaited, a sync one called inline.

    Inline rather than in the executor, because a selector returns a queryset
    nobody has evaluated yet and building one runs no query. A sync selector
    that does query when called has to be run in the executor by its caller,
    as dispatch runs everything but the selector.
    """
    if is_async(fn):
        return await fn(**kwargs)
    return fn(**kwargs)
