from __future__ import annotations

import inspect
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.pool.null_progress import null_progress
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.pool.utils import pool_kwargs
from django_service_specs.types.progress_reporter import ProgressReporter


def base_pool(
    *,
    user: Any,
    progress: ProgressReporter | None = None,
    seeds: PoolSeeds = DEFAULT_POOL_SEEDS,
    **extra: Any,
) -> dict[str, Any]:
    """The seeds a dispatched callable's kwargs pool carries, on every transport."""
    pool: dict[str, Any] = {
        "user": user,
        "progress": null_progress if progress is None else progress,
        **extra,
    }
    bound = dict(pool)
    for name, resolver in seeds.resolvers().items():
        if name in bound:
            raise TypeError(
                f"base_pool() got a registered pool seed {name!r} that an entry already "
                f"occupies. A seed cannot silently outrank what the caller spread in."
            )
        pool[name] = _settled(name, resolver(**pool_kwargs(resolver, bound)))
    return pool


def _settled(name: str, value: Any) -> Any:
    """Return a seed's resolved ``value``, refusing one that is still to be awaited."""
    if inspect.isawaitable(value) or inspect.isasyncgen(value):
        if inspect.iscoroutine(value):
            value.close()
        raise ImproperlyConfigured(
            f"The pool seed {name!r} resolved to an awaitable ({type(value).__name__}). A "
            "resolver is called from sync code and never awaited, so the value is refused "
            "rather than seeded, where it would read as true; declare the resolver with def."
        )
    return value
