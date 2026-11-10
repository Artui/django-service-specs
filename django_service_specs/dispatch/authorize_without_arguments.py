from __future__ import annotations

from dataclasses import replace
from typing import Any

from django_service_specs.dispatch.authorize import authorize
from django_service_specs.dispatch.authorize_scope import authorize_scope
from django_service_specs.dispatch.grant import Grant
from django_service_specs.dispatch.utils import asks_scope_of_nothing
from django_service_specs.pool.pool_seeds import PoolSeeds
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource


def authorize_without_arguments(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    principal: Any,
    *,
    grant: Grant | None = None,
    call_context: dict[str, Any] | None = None,
    pool_seeds: PoolSeeds | None = None,
) -> Grant:
    """Ask ``spec``'s permission checks for ``principal`` as a call with no arguments would."""
    spec = kernel_spec(spec)
    call_context = {} if call_context is None else call_context
    granted = authorize(
        spec,
        principal,
        grant=grant,
        arguments=None,
        call_context=call_context,
        pool_seeds=pool_seeds,
    )
    if asks_scope_of_nothing(spec):
        authorize_scope(
            spec,
            principal,
            None,
            grant=replace(granted, target_checked=False),
            arguments=None,
            call_context=call_context,
            pool_seeds=pool_seeds,
        )
    return granted
