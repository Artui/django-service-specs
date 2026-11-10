from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django_service_specs.pool.call_seeds import CALL_SEEDS
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.pool.provider_keys import provider_keys
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.validation.validator_parameters import validator_parameters


def server_owned_keys(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    *,
    pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS,
    call_context: dict[str, Any] | None = None,
) -> frozenset[str]:
    """Every name ``spec``'s dispatch fills from the server, whatever the caller sends."""
    spec = kernel_spec(spec)
    owned: set[str] = set(pool_seeds.reserved)
    if isinstance(spec, ServiceSpec) and spec.validator is not None and not spec.many:
        declared = validator_parameters(spec.validator, call_context=call_context)
        owned -= declared.names() & pool_seeds.names
    providers: list[Callable[..., Any] | None] = [spec.kwargs]
    reads = [spec.reads]
    if isinstance(spec, ServiceSpec):
        target = spec.target_selector_spec()
        providers += [spec.input_data, None if target is None else target.kwargs]
        if target is not None:
            reads.append(target.reads)
    owned |= CALL_SEEDS & {param.name for seat in reads for param in seat if param.reflected}
    for provider in providers:
        keys = provider_keys(provider)
        if keys is not None:
            owned |= keys.filled
    return frozenset(owned)
