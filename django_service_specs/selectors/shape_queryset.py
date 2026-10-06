"""``shape_queryset`` — apply a selector spec's queryset-shaping fields."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.selectors.utils import apply_shaping
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

    It answers no ``affordances``. Dispatch answers a selector spec's in the
    same ``.annotate()`` call, with the call's registered seeds, which this is
    not handed; a transport that shapes rows here and then presents them
    through a spec declaring ``affordances`` is refused at ``present``.

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
    # Nothing is the caller's to fill here: a transport shaping rows itself
    # has bound no arguments, so a parameter the pool lacks raises as the
    # callable's own error, as it always has.
    return apply_shaping(
        queryset,
        spec,
        pool,
        annotations=spec.annotations,
        source_label=source_label,
        fillable=frozenset(),
    )
