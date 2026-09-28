"""``shape_queryset`` — apply a selector spec's queryset-shaping fields."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.pool.resolve_callable_kwargs import resolve_callable_kwargs
from django_service_specs.selectors.utils import is_queryset
from django_service_specs.specs.selector_spec import SelectorSpec


def shape_queryset(
    queryset: Any,
    spec: SelectorSpec,
    pool: Mapping[str, Any],
    *,
    source_label: str,
) -> Any:
    """Apply ``spec``'s shaping fields to ``queryset``, in the fixed order.

    ``select_related``, ``prefetch_related`` and ``annotations`` run first, in
    declaration order, so ``extend_queryset`` always sees the fully
    declaratively-shaped queryset. ``extend_queryset`` is resolved from
    ``{**pool, "queryset": queryset}`` through the same declare-to-receive rule
    as every other pool-resolved callable, and its return is the shaped
    queryset from here on.

    Args:
        source_label: Named in the misconfiguration error to point at the
            offending spec (``"SelectorSpec.selector"`` vs
            ``"ServiceSpec.output_selector_spec.selector"``).

    Returns:
        The shaped queryset, or ``queryset`` unchanged when nothing is
        configured.

    Raises:
        ImproperlyConfigured: Shaping is configured but ``queryset`` is not a
            Django queryset — loud failure beats a stray ``AttributeError``
            deep inside whichever transport renders the result.
    """
    if (
        spec.select_related is None
        and spec.prefetch_related is None
        and spec.annotations is None
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
    if spec.annotations is not None:
        queryset = queryset.annotate(**spec.annotations)
    if spec.extend_queryset is not None:
        extend_pool = {**pool, "queryset": queryset}
        queryset = spec.extend_queryset(
            **resolve_callable_kwargs(spec.extend_queryset, extend_pool)
        )
    return queryset
