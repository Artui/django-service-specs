from __future__ import annotations

from typing import Any

from asgiref.sync import sync_to_async

from django_service_specs.affordances.enforce_affordances import enforce_affordances
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource


async def aenforce_affordances(
    spec: ServiceSpec | SpecSource,
    pool: dict[str, Any],
    *,
    instance: Any,
    reserved: frozenset[str],
    call_context: dict[str, Any] | None = None,
) -> None:
    """The async form of ``enforce_affordances``: one thread hop for every condition."""
    compiled = kernel_spec(spec)
    if isinstance(compiled, ServiceSpec) and not compiled.affordances:
        return
    await sync_to_async(enforce_affordances, thread_sensitive=True)(
        spec,
        pool,
        instance=instance,
        reserved=reserved,
        call_context=call_context,
    )
