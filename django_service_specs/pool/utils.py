"""Helpers shared across the readers of a spec's providers, which dispatch calls."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from django.core.exceptions import ImproperlyConfigured

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
    ``UNSET``, so the caller's value survives the merge rather than a
    fallback ``None`` silently widening a scope. Declining is for benign keys
    only; a provider owning a scoping key must always answer it.

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
    service, as a transport's reporter failing does today; and a provider that
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
