from __future__ import annotations

from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.types.selector_kind import SelectorKind


def can_present_nothing(spec: ServiceSpec | SelectorSpec | SpecSource) -> bool:
    """Whether a successful dispatch of ``spec`` may present ``None`` as its result."""
    spec = kernel_spec(spec)
    if isinstance(spec, SelectorSpec):
        return spec.kind is SelectorKind.RETRIEVE and spec.allow_none
    reread = spec.output_selector_spec
    if reread is not None:
        return reread.kind is SelectorKind.RETRIEVE
    return spec.allow_none
