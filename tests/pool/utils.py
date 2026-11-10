from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any


def passthrough(provider: Callable[..., Any]) -> Callable[..., Any]:
    """``provider`` behind a wrapper defined here, as a decorator from another package would be."""

    @functools.wraps(provider)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return provider(*args, **kwargs)

    return wrapper
