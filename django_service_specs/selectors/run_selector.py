from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from asgiref.sync import async_to_sync

from django_service_specs.types.is_async import is_async


def run_selector(fn: Callable[..., Any], kwargs: Mapping[str, Any]) -> Any:
    """Call a selector from sync code, transparently bridging an async one."""
    if is_async(fn):
        return async_to_sync(fn)(**kwargs)
    return fn(**kwargs)
