from __future__ import annotations

from typing import Any

from asgiref.sync import sync_to_async

from django_service_specs.affordances.operation_affordances import operation_affordances
from django_service_specs.affordances.unmet_operation_affordance import (
    unmet_operation_affordance,
)
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.types.affordance import Affordance


async def aunmet_operation_affordance(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    pool: dict[str, Any],
    *,
    reserved: frozenset[str],
    call_context: dict[str, Any] | None = None,
) -> Affordance | None:
    """The async form of ``unmet_operation_affordance``, answering in one thread hop."""
    compiled = kernel_spec(spec)
    if not operation_affordances(compiled):
        return None
    return await sync_to_async(unmet_operation_affordance, thread_sensitive=True)(
        compiled, pool, reserved=reserved, call_context=call_context
    )
