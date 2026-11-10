from __future__ import annotations

from typing import Any

from django_service_specs.authorization.utils import (
    QUESTIONS,
    refuse_deactivated,
    seeds_for_checks,
)
from django_service_specs.dispatch.call_seeds import CallSeeds
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource


def resolve_seeds(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    *,
    principal: Any,
    pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS,
    call_context: dict[str, Any] | None = None,
) -> CallSeeds:
    """The registered seeds ``spec``'s checks name, resolved for ``principal``, as a carrier."""
    refuse_deactivated(principal)
    context = {} if call_context is None else call_context
    values = seeds_for_checks(
        kernel_spec(spec), principal, pool_seeds, QUESTIONS, call_context=context
    )
    return CallSeeds(spec, principal, context, pool_seeds, values)
