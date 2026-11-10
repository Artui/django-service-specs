from __future__ import annotations

from typing import Any

from django_service_specs.affordances.operation_affordances import operation_affordances
from django_service_specs.affordances.utils import answer_operation_condition, with_call_context
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.types.affordance import Affordance


def unmet_operation_affordance(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    pool: dict[str, Any],
    *,
    reserved: frozenset[str],
    call_context: dict[str, Any] | None = None,
) -> Affordance | None:
    """The first of the spec's operation-scope affordances not met now, or ``None``."""
    pool = with_call_context(pool, call_context)
    for affordance in operation_affordances(spec):
        if not answer_operation_condition(affordance.when, pool, reserved=reserved):
            return affordance
    return None
