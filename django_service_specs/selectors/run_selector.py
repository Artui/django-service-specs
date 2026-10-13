"""``run_selector`` - call a selector from sync code, whichever kind it is."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from asgiref.sync import async_to_sync

from django_service_specs.services.is_async import is_async


def run_selector(fn: Callable[..., Any], kwargs: Mapping[str, Any]) -> Any:
    """Call a selector from sync code, transparently bridging an async one.

    A selector is the one callable a ``SelectorSpec`` may make ``async def``;
    every other concept in the spec is sync-only and runs in the executor. The
    bridge keeps sync code from ever seeing an un-awaited coroutine.

    ``kwargs`` is what the selector is called with, already bound: resolve it
    from a pool first, as dispatch does.
    """
    if is_async(fn):
        return async_to_sync(fn)(**kwargs)
    return fn(**kwargs)
