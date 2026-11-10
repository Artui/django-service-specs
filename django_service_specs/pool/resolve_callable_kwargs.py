from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from django_service_specs.types.utils import BY_NAME_ONLY_POOL_NAMES


def resolve_callable_kwargs(
    fn: Callable[..., Any],
    pool: dict[str, Any],
) -> dict[str, Any]:
    """Pick the subset of ``pool`` matching ``fn``'s declared parameters."""
    params = inspect.signature(fn).parameters.values()
    named = [
        param.name
        for param in params
        if param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    ]
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params):
        return {
            name: value
            for name, value in pool.items()
            if name not in BY_NAME_ONLY_POOL_NAMES or name in named
        }
    return {name: pool[name] for name in named if name in pool}
