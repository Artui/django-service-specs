from __future__ import annotations

from typing import Any

from django_service_specs.dispatch.relax_partial import relax_partial
from django_service_specs.schema.parameters_schema import parameters_schema
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.types.unknown_arguments import UnknownArguments


def spec_input_schema(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    *,
    unknown_arguments: UnknownArguments = UnknownArguments.REJECT,
    call_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """``parameters_schema`` over ``spec.parameters()``."""
    spec = kernel_spec(spec)
    parameters = relax_partial(spec, spec.parameters(call_context=call_context))
    return parameters_schema(parameters, unknown_arguments=unknown_arguments)
