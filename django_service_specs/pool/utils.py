"""Helpers shared across the readers of a spec's providers, which dispatch calls, and of its seeds."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.pool.base_pool import base_pool
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.pool.resolve_callable_kwargs import resolve_callable_kwargs
from django_service_specs.types.progress_reporter import ProgressReporter
from django_service_specs.types.unset import UNSET


def resolve_provider(
    provider: Callable[..., Any] | None, pool: Mapping[str, Any], *, label: str
) -> dict[str, Any]:
    """Call a ``kwargs`` or ``input_data`` provider from ``pool``, and keep what it fills.

    Bound by ``resolve_callable_kwargs``, as every pool-resolved callable is,
    so a provider names what it reads - ``user``, a seed, a ``reads``
    argument - or takes ``**kwargs`` for the whole pool. A key whose value is
    ``UNSET`` is dropped: the provider is declining it, not setting it to
    ``UNSET``, so the key is left to the caller rather than a fallback
    ``None`` silently widening a scope. Whose value that is depends on how the
    key is annotated: one declared ``declinable`` (its value admits
    ``UnsetType``), or any key of an untyped provider, keeps the caller's
    value; one the provider is annotated to fill is the server's, and dispatch
    dropped the caller's value for it after the shape check, so declining it
    leaves it absent and the step that reads it refuses the call. So a scoping
    key belongs in a ``TypedDict`` that does not admit ``UNSET``.

    ``label`` names the field in the refusal of a return that is no mapping,
    which would otherwise surface as an ``AttributeError`` from inside the
    merge.
    """
    if provider is None:
        return {}
    resolved = provider(**resolve_callable_kwargs(provider, dict(pool)))
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
    """The reporter a run reports to: the ``transport``'s, and the spec's own sink.

    ``provider`` is a spec's ``progress_reporter``. It is **resolved on first
    use**: called from ``pool`` the first time the run reports, and never
    before, so a call refused before its run - by the shape check, a
    permission, a missing row, the Validator, an affordance or a precondition
    - never calls it, and a run that never reports never does either. It is
    called once; a provider returning ``None`` declines, and the transport's
    reporter is the only one that hears.

    Each report goes to the transport's reporter first, then to the spec's
    sink. A failure in either propagates to the caller of the report, the
    service, as a transport's reporter failing does; and a provider that
    raises does so there too, inside the run's transaction rather than before
    it.

    ``transport`` is the reporter the caller handed dispatch, or ``None``.
    With no provider this is ``transport`` itself, so a spec declaring none
    costs nothing and a pool still falls back to ``null_progress`` on ``None``.

    Not for an ``async def`` service: its first report runs on the event
    loop, and a provider that queries - finding or creating a task record is
    the common one - raises ``SynchronousOnlyOperation`` there and nowhere
    else. ``resolve_progress`` resolves it at once, from sync code, for that.
    """
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
            resolved.append(provider(**resolve_callable_kwargs(provider, dict(pool))))
        _fan(transport, resolved[0])(progress, total=total, message=message, meta=meta)

    return report


def resolve_progress(
    provider: Callable[..., Any] | None,
    pool: Mapping[str, Any],
    *,
    transport: ProgressReporter | None,
) -> ProgressReporter | None:
    """``deferred_progress``, with the provider called now rather than on the first report.

    For a dispatch path that must call the provider from sync code before the
    run - an ``async def`` service reports from the event loop, where a
    provider that queries cannot run. Called after every check that can
    refuse the call, it keeps the same promise: a refused call never calls the
    provider. A provider returning ``None`` declines, as there.
    """
    if provider is None:
        return transport
    return _fan(transport, provider(**resolve_callable_kwargs(provider, dict(pool))))


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
    """``pool_seeds`` narrowed to ``names``, in registration order.

    What resolves a part of a registry and leaves the rest for later: the
    seeds a call's checks name, before the class-level check, and every other
    seed after it.
    """
    return DEFAULT_POOL_SEEDS.extend(
        **{name: resolver for name, resolver in pool_seeds.resolvers().items() if name in names}
    )


def resolved_seeds(pool_seeds: PoolSeeds, names: frozenset[str], *, user: Any) -> dict[str, Any]:
    """The seeds of ``pool_seeds`` that ``names`` names, resolved for ``user``, and no other.

    What resolves a seed ahead of a call's pools, for whatever named it: a
    permission check before the class-level check (``seeds_for_checks``). A
    name the registry does not hold is skipped, so the caller passes every
    name its callable declares and only the registered ones resolve
    (test_only_the_named_seeds_resolve_and_an_unregistered_name_is_skipped). From a
    base pool with no live reporter, so a resolver reading ``progress`` sees
    the no-op one; a resolver that raises ends the call here.
    """
    named = names & pool_seeds.names
    resolved = base_pool(user=user, seeds=only_seeds(pool_seeds, named))
    return {name: resolved[name] for name in named}
