from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.selectors.utils import apply_shaping
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.spec_source import SpecSource


def shape_queryset(
    queryset: Any,
    spec: SelectorSpec | SpecSource,
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
        TypeError: ``spec`` is, or compiles to, a ``ServiceSpec``, which
            declares no shaping of its own: its reads are shaped by the
            selector specs it nests.
    """
    compiled = kernel_spec(spec)
    if not isinstance(compiled, SelectorSpec):
        raise TypeError(
            f"shape_queryset() takes a SelectorSpec; got {type(compiled).__name__}, whose reads "
            "are shaped by the selector specs it nests."
        )
    return apply_shaping(
        queryset,
        compiled,
        pool,
        annotations=compiled.annotations,
        source_label=source_label,
        fillable=frozenset(),
    )
