"""``aenforce_affordances`` - the async twin of ``enforce_affordances``."""

from __future__ import annotations

from typing import Any

from asgiref.sync import sync_to_async

from django_service_specs.affordances.enforce_affordances import enforce_affordances
from django_service_specs.pool.reserved_pool_seeds import RESERVED_POOL_SEEDS
from django_service_specs.specs.service_spec import ServiceSpec


async def aenforce_affordances(
    spec: ServiceSpec,
    pool: dict[str, Any],
    *,
    instance: Any,
    reserved: frozenset[str] = RESERVED_POOL_SEEDS,
) -> None:
    """[`enforce_affordances`][django_service_specs.affordances.enforce_affordances.enforce_affordances] for an async caller.

    For a transport that runs a service without
    [`adispatch`][django_service_specs.dispatch.adispatch.adispatch], which
    answers a spec's affordances inside its own hop. It refuses and lets through
    exactly as the sync function does, with the same arguments.

    A condition on the row is a query and a callable condition is user code
    that may query, and neither can run on the event loop. So every condition
    is answered in **one** ``sync_to_async(thread_sensitive=True)`` hop, as
    dispatch's async path runs every sync concept: not one hop per condition.
    A spec declaring none returns before the hop, so declaring nothing costs
    the async path nothing.

    Raises:
        ActionUnavailable: An affordance is not met.
        ServiceNotFound: A condition on the row was reached and the row is gone.
        ImproperlyConfigured: A condition on the row was reached and
            ``instance`` is not a model instance.
    """
    if not spec.affordances:
        return
    await sync_to_async(enforce_affordances, thread_sensitive=True)(
        spec, pool, instance=instance, reserved=reserved
    )
