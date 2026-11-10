from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from django_service_specs.authorization.utils import refuse_deactivated
from django_service_specs.dispatch.utils import (
    seat_seed_named,
    seeded_base,
    shape_check,
    target_entry,
    validate_arguments,
)
from django_service_specs.pool.pool_seeds import PoolSeeds
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.types.unknown_arguments import UnknownArguments


def bind_arguments(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    arguments: Mapping[str, Any],
    *,
    principal: Any,
    target: Any = None,
    unknown_arguments: UnknownArguments = UnknownArguments.REJECT,
    call_context: dict[str, Any] | None = None,
    pool_seeds: PoolSeeds | None = None,
) -> dict[str, Any]:
    """Check ``arguments`` against the spec's parameters, then validate them."""
    spec = kernel_spec(spec)
    context = {} if call_context is None else call_context
    parameters = spec.parameters(call_context=context)
    if pool_seeds is not None:
        refuse_deactivated(principal)
        parameters = seat_seed_named(spec, parameters, parameters, pool_seeds, call_context=context)
    checked = shape_check(
        spec, parameters, arguments, unknown_arguments=unknown_arguments, call_context=context
    )
    if isinstance(spec, SelectorSpec):
        return checked
    ambient: dict[str, Any] = {}
    if pool_seeds is not None and spec.validator is not None:
        ambient = seeded_base(
            principal, progress=None, pool_seeds=pool_seeds, early={}, call_context=context
        )
    validated = validate_arguments(
        spec,
        checked,
        principal=principal,
        target=target,
        server_input={},
        call_context=context,
        provider_answered=False,
        ambient=MappingProxyType(ambient),
        resolved=target_entry(spec, target),
    )
    return validated.values
