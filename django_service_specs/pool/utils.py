from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.pool.call_seeds import CALL_SEEDS
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.pool.resolve_callable_kwargs import resolve_callable_kwargs
from django_service_specs.types.progress_reporter import ProgressReporter
from django_service_specs.types.unset import UNSET
from django_service_specs.types.utils import CALL_CONTEXT


def resolve_provider(
    provider: Callable[..., Any] | None, pool: Mapping[str, Any], *, label: str
) -> dict[str, Any]:
    """Call a ``kwargs`` or ``input_data`` provider from ``pool``, and keep what it fills."""
    if provider is None:
        return {}
    resolved = provider(**pool_kwargs(provider, pool))
    if not isinstance(resolved, Mapping):
        raise ImproperlyConfigured(
            f"{label} returned {type(resolved).__name__}; a provider returns a mapping of "
            "pool entries."
        )
    return {key: value for key, value in resolved.items() if value is not UNSET}


def deferred_progress(
    provider: Callable[..., Any] | None,
    pool: Mapping[str, Any],
    *,
    transport: ProgressReporter | None,
) -> ProgressReporter | None:
    """The reporter a run reports to: the ``transport``'s, and the spec's own sink."""
    if provider is None:
        return transport
    resolved: list[ProgressReporter | None] = []

    def report(
        progress: float,
        *,
        total: float | None = None,
        message: str | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> None:
        if not resolved:
            resolved.append(provider(**pool_kwargs(provider, pool)))
        _fan(transport, resolved[0])(progress, total=total, message=message, meta=meta)

    return report


def resolve_progress(
    provider: Callable[..., Any] | None,
    pool: Mapping[str, Any],
    *,
    transport: ProgressReporter | None,
) -> ProgressReporter | None:
    """``deferred_progress``, with the provider called now rather than on the first report."""
    if provider is None:
        return transport
    return _fan(transport, provider(**pool_kwargs(provider, pool)))


def _fan(transport: ProgressReporter | None, own: ProgressReporter | None) -> ProgressReporter:
    """One reporter handing each report to ``transport``, then to ``own``, skipping a ``None``."""

    def report(
        progress: float,
        *,
        total: float | None = None,
        message: str | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> None:
        for sink in (transport, own):
            if sink is not None:
                sink(progress, total=total, message=message, meta=meta)

    return report


def only_seeds(pool_seeds: PoolSeeds, names: frozenset[str]) -> PoolSeeds:
    """``pool_seeds`` narrowed to ``names``, in registration order."""
    return DEFAULT_POOL_SEEDS.extend(
        **{name: resolver for name, resolver in pool_seeds.resolvers().items() if name in names}
    )


def call_entries(call_context: Mapping[str, Any] | None) -> dict[str, Any]:
    """The call's ``request`` and ``view``, read off ``call_context``; ``None`` if absent."""
    context = {} if call_context is None else call_context
    return {name: context.get(name) for name in sorted(CALL_SEEDS)}


def pool_kwargs(fn: Callable[..., Any], pool: Mapping[str, Any]) -> dict[str, Any]:
    """``resolve_callable_kwargs``, with the call's ``request`` and ``view`` where named."""
    kwargs = resolve_callable_kwargs(fn, dict(pool))
    if CALL_CONTEXT not in pool:
        return kwargs
    entries = call_entries(pool[CALL_CONTEXT])
    declared = {
        param.name
        for param in inspect.signature(fn).parameters.values()
        if param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    return {**{name: entries[name] for name in sorted(declared & CALL_SEEDS)}, **kwargs}
