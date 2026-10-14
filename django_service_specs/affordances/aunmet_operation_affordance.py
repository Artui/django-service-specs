"""``aunmet_operation_affordance`` - the async twin of ``unmet_operation_affordance``."""

from __future__ import annotations

from typing import Any

from asgiref.sync import sync_to_async

from django_service_specs.affordances.operation_affordances import operation_affordances
from django_service_specs.affordances.unmet_operation_affordance import (
    unmet_operation_affordance,
)
from django_service_specs.pool.reserved_pool_seeds import RESERVED_POOL_SEEDS
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance


async def aunmet_operation_affordance(
    spec: ServiceSpec | SelectorSpec,
    pool: dict[str, Any],
    *,
    reserved: frozenset[str] = RESERVED_POOL_SEEDS,
) -> Affordance | None:
    """[`unmet_operation_affordance`][django_service_specs.affordances.unmet_operation_affordance.unmet_operation_affordance] for an async caller.

    For a transport building its list of operations on an event loop: an MCP
    server answering a tool list, an agent assembling its next step's tools.
    It gives the sync function's answer for the same arguments.

    A callable condition is user code and may query, so the conditions are
    answered in **one** ``sync_to_async(thread_sensitive=True)`` hop, as
    dispatch's async path runs every sync concept. A spec with nothing to ask
    at list time - nothing in
    [`operation_affordances`][django_service_specs.affordances.operation_affordances.operation_affordances],
    which is every ``SelectorSpec`` and every spec declaring only conditions on
    the row - returns ``None`` before the hop: a transport asks this for every
    operation it lists, and most declare nothing.

    A caller that must release a connection a condition opens - a long-lived
    agent run, a worker with its own event loop - makes its own hop instead,
    calls ``unmet_operation_affordance`` inside it, and releases the connection
    in that same hop.
    """
    if not operation_affordances(spec):
        return None
    return await sync_to_async(unmet_operation_affordance, thread_sensitive=True)(
        spec, pool, reserved=reserved
    )
