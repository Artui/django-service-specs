"""Private selector-dispatch helpers, shared across ``selectors/``.

Not exported from ``selectors/__init__.py`` — ``shape_queryset`` is the
subpackage's public surface. These are used by it, and by the dispatch core
once it lands.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from asgiref.sync import async_to_sync
from django.core.exceptions import ImproperlyConfigured
from django.db.models import QuerySet
from django.db.models.manager import BaseManager

from django_service_specs.pool.resolve_callable_kwargs import resolve_callable_kwargs
from django_service_specs.services.is_async import is_async
from django_service_specs.specs.selector_spec import SelectorSpec


def is_queryset(obj: Any) -> bool:
    """True for Django ``QuerySet`` objects and ``Manager`` instances.

    The one definition of a queryset-shaping target: what the shaping fields
    may be applied to, and what a RETRIEVE selector materializes from. Tested
    by type rather than by ``hasattr(…, "first")``, which would also match a
    domain object that happens to expose ``first``. ``QuerySet`` subclasses all
    pass.
    """
    return isinstance(obj, (QuerySet, BaseManager))


def materialize_retrieve(result: Any) -> Any:
    """Collapse a RETRIEVE selector's return to the single instance, or ``None``.

    The one definition of what ``kind=RETRIEVE`` means once the selector has
    run: a queryset materializes through ``.first()`` — so an author can write
    ``selector=lambda *, pk: Model.objects.filter(pk=pk)`` and still get the
    spec's shaping applied first — and anything else passes through as the
    resolved object. What each caller does with a ``None`` differs; how the
    value is arrived at does not.
    """
    return result.first() if is_queryset(result) else result


def call_selector(fn: Callable[..., Any], kwargs: dict[str, Any]) -> Any:
    """Call a selector from sync code, transparently bridging an async one.

    A selector is the one callable a ``SelectorSpec`` may make ``async def``;
    every other concept in the spec is sync-only and runs in the executor. The
    bridge keeps the sync dispatch core from ever seeing an un-awaited
    coroutine.
    """
    if is_async(fn):
        return async_to_sync(fn)(**kwargs)
    return fn(**kwargs)


def apply_shaping(
    queryset: Any,
    spec: SelectorSpec,
    pool: Mapping[str, Any],
    *,
    annotations: Mapping[str, Any] | None,
    source_label: str,
) -> Any:
    """``shape_queryset``, with the annotations it applies named by the caller.

    ``shape_queryset`` passes the spec's own. Dispatch passes them with every
    affordance answer the spec declares beside them, built against the model
    the selector returned, so each answer rides in the one ``.annotate()`` call
    and ``extend_queryset`` sees the answers as it sees a declared annotation.
    The public function cannot build them itself: a callable condition is
    answered against the call's registered seeds, which it is not handed.
    """
    if (
        spec.select_related is None
        and spec.prefetch_related is None
        and annotations is None
        and spec.extend_queryset is None
    ):
        return queryset
    if not is_queryset(queryset):
        raise ImproperlyConfigured(
            "select_related / prefetch_related / annotations / extend_queryset "
            f"are set on the spec but {source_label} returned "
            f"{type(queryset).__name__}, which is not a Django QuerySet. Drop "
            "the shaping fields or have the callable return a QuerySet."
        )
    if spec.select_related is not None:
        queryset = queryset.select_related(*spec.select_related)
    if spec.prefetch_related is not None:
        queryset = queryset.prefetch_related(*spec.prefetch_related)
    if annotations is not None:
        queryset = queryset.annotate(**annotations)
    if spec.extend_queryset is not None:
        extend_pool = {**pool, "queryset": queryset}
        queryset = spec.extend_queryset(
            **resolve_callable_kwargs(spec.extend_queryset, extend_pool)
        )
    return queryset
