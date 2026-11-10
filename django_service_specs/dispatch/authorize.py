from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.permission_check_denied import PermissionCheckDenied
from django_service_specs.authorization.sync_answer import sync_answer
from django_service_specs.authorization.utils import (
    CLASS_LEVEL,
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


def authorize(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    principal: Any,
    *,
    grant: Grant | None = None,
    arguments: Mapping[str, Any] | None = None,
    call_context: dict[str, Any] | None = None,
    seeds: Mapping[str, Any] | CallSeeds | None = None,
    pool_seeds: PoolSeeds | None = None,
) -> Grant:
    """Run ``spec``'s class-level permission checks for ``principal``."""
    if isinstance(seeds, CallSeeds):
        refuse_deactivated(principal)
        registry = DEFAULT_POOL_SEEDS if pool_seeds is None else pool_seeds
        seeds = seeds.values_for(spec, principal, call_context, registry)
        pool_seeds = None
    check_seed_arguments(principal, seeds=seeds, pool_seeds=pool_seeds, asked="authorize")
    spec = kernel_spec(spec)
    if grant is not None:
        if grant.covers(spec, principal):
            return grant
        raise NotPermitted("The grant does not cover this spec and principal.")
    if spec.permissions is None:
        run = getattr(spec, "service", None) or getattr(spec, "selector", None)
        raise ImproperlyConfigured(
            f"The {type(spec).__name__} for {getattr(run, '__qualname__', run)!s} declares "
            "no permissions. Pass permissions=[Unrestricted()] to mean that anyone may run it."
        )
    offered = offered_to_checks(
        call_context,
        offered_seeds(
            spec,
            principal,
            seeds=seeds,
            pool_seeds=pool_seeds,
            question=CLASS_LEVEL,
            call_context=call_context,
        ),
    )
    for check in spec.permissions:
        answer = check.has_permission(
            principal, spec, **asked_with(check, "has_permission", arguments, offered=offered)
        )
        if not sync_answer(answer, asked=f"{type(check).__qualname__}.has_permission"):
            raise PermissionCheckDenied(check=check, spec=spec)
    return Grant(spec, principal)
