from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.authorization.permission_check_denied import PermissionCheckDenied
from django_service_specs.authorization.sync_answer import sync_answer
from django_service_specs.authorization.utils import (
    SCOPE_LEVEL,
    asked_with,
    check_seed_arguments,
    offered_seeds,
    offered_to_checks,
    refuse_deactivated,
)
from django_service_specs.dispatch.call_seeds import CallSeeds
from django_service_specs.dispatch.grant import Grant
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource


def authorize_scope(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    principal: Any,
    scope: Any,
    *,
    grant: Grant,
    arguments: Mapping[str, Any] | None = None,
    call_context: dict[str, Any] | None = None,
    seeds: Mapping[str, Any] | CallSeeds | None = None,
    pool_seeds: PoolSeeds | None = None,
) -> None:
    """Run ``spec``'s scope-level permission checks against ``scope``."""
    if isinstance(seeds, CallSeeds):
        refuse_deactivated(principal)
        registry = DEFAULT_POOL_SEEDS if pool_seeds is None else pool_seeds
        seeds = seeds.values_for(spec, principal, call_context, registry)
        pool_seeds = None
    check_seed_arguments(principal, seeds=seeds, pool_seeds=pool_seeds, asked="authorize_scope")
    spec = kernel_spec(spec)
    if grant.target_checked:
        return
    offered = offered_to_checks(
        call_context,
        offered_seeds(
            spec,
            principal,
            seeds=seeds,
            pool_seeds=pool_seeds,
            question=SCOPE_LEVEL,
            call_context=call_context,
        ),
    )
    for check in spec.permissions or ():
        answer = check.has_scope_permission(
            principal,
            spec,
            scope,
            **asked_with(check, "has_scope_permission", arguments, positional=3, offered=offered),
        )
        if not sync_answer(answer, asked=f"{type(check).__qualname__}.has_scope_permission"):
            raise PermissionCheckDenied(check=check, spec=spec)
