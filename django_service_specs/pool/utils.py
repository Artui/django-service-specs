"""Helpers shared across the readers of a spec's providers, which dispatch calls, and of its seeds."""

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
    """Call a ``kwargs`` or ``input_data`` provider from ``pool``, and keep what it fills.

    Bound by ``pool_kwargs``, as every callable dispatch resolves is,
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
            resolved.append(provider(**pool_kwargs(provider, pool)))
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
    """``pool_seeds`` narrowed to ``names``, in registration order.

    What resolves a part of a registry and leaves the rest for later: the
    seeds a call's checks name, before the class-level check, and every other
    seed after it.
    """
    return DEFAULT_POOL_SEEDS.extend(
        **{name: resolver for name, resolver in pool_seeds.resolvers().items() if name in names}
    )


def call_entries(call_context: Mapping[str, Any] | None) -> dict[str, Any]:
    """The call's ``request`` and ``view``, read off ``call_context``: ``None`` for a key it lacks.

    The very objects the context holds, never copies
    (test_a_service_spec_s_stages_are_handed_the_context_s_request_and_view),
    and ``None`` for both when there is no context at all. One definition for
    ``pool_kwargs``, which binds every callable dispatch resolves and every
    affordance condition and ``form_kwargs`` asked outside it, and for every
    check the ``authorize`` functions ask, so none of them can read the two
    differently.
    """
    context = {} if call_context is None else call_context
    return {name: context.get(name) for name in sorted(CALL_SEEDS)}


def pool_kwargs(fn: Callable[..., Any], pool: Mapping[str, Any]) -> dict[str, Any]:
    """``resolve_callable_kwargs``, with the call's ``request`` and ``view`` for a callable naming one.

    The binder every callable dispatch resolves goes through. The two are
    never pool entries: a pool carrying the call's context hands each to a
    callable declaring it, read off that context (``None`` where it holds
    none), and never to a ``**kwargs`` catch-all, as the context itself is
    handed (test_a_catch_all_is_handed_neither). A mount that registers either
    name has it in the pool, where the seed reaches a callable as any entry
    does, a catch-all included; the pool's own value is merged last, which is
    what makes it outrank the context's
    (test_the_registered_seed_supplies_the_name fails with the order flipped).
    A pool with no ``call_context``, as a transport builds its own, binds as
    ``resolve_callable_kwargs`` binds it
    (test_a_pool_with_no_call_context_binds_as_published). The public binder
    stays as published, since the transports bind their own pools through it.
    """
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
