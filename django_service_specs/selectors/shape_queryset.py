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
    """Apply ``spec``'s shaping fields to ``queryset``, in the fixed order."""
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
