from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any


def is_async(fn: Callable[..., Any]) -> bool:
    """Return True if calling ``fn(...)`` produces a coroutine."""
    if inspect.iscoroutinefunction(fn):
        return True
    cls_call: Any = getattr(type(fn), "__call__", None)  # noqa: B004
    return cls_call is not None and inspect.iscoroutinefunction(cls_call)
