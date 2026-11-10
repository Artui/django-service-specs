from __future__ import annotations

from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.types.affordance import Affordance
from django_service_specs.types.utils import is_row_condition


def operation_affordances(
    spec: ServiceSpec | SelectorSpec | SpecSource,
) -> tuple[Affordance, ...]:
    """The operation-scope affordances ``spec`` declares, in declaration order."""
    spec = kernel_spec(spec)
    if isinstance(spec, SelectorSpec):
        return ()
    return tuple(
        affordance for affordance in spec.affordances or () if not is_row_condition(affordance.when)
    )
