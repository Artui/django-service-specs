from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from django_service_specs.types.is_async import is_async


async def arun_selector(
    fn: Callable[..., Any] | Callable[..., Awaitable[Any]], kwargs: Mapping[str, Any]
) -> Any:
    """Call a selector from async code: awaited if ``async def``, else called inline."""
    if is_async(fn):
        return await fn(**kwargs)
    return fn(**kwargs)
