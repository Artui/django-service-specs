from __future__ import annotations

from typing import Any

from django_service_specs.dispatch.utils import reach, server_filled
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.validation.validator_parameters import validator_parameters


def provider_reached(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    *,
    call_context: dict[str, Any] | None = None,
) -> frozenset[str]:
    """Every top-level parameter of ``spec`` a provider fills or may fill."""
    spec = kernel_spec(spec)
    reached = server_filled(spec)[1]
    if isinstance(spec, ServiceSpec) and spec.validator is not None and not spec.many:
        fields = validator_parameters(spec.validator, call_context=call_context)
        reached |= reach(spec.input_data, fields)[1]
    return reached
