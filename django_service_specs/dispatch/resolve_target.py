from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.dispatch.call_seeds import CallSeeds
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.grant import Grant
from django_service_specs.dispatch.resolved_target import ResolvedTarget
from django_service_specs.dispatch.utils import CheckKeywords, open_call, walk_target
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.types.unknown_arguments import UnknownArguments


def resolve_target(
    spec: ServiceSpec | SpecSource,
    *,
    principal: Any,
    arguments: Mapping[str, Any],
    grant: Grant | None = None,
    pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS,
    call_context: dict[str, Any] | None = None,
    seeds: CallSeeds | None = None,
) -> ResolvedTarget | DispatchResult:
    """Find and check ``spec``'s target as ``dispatch`` would, without running anything else."""
    if seeds is not None and not isinstance(seeds, CallSeeds):
        raise TypeError(
            "resolve_target() takes as seeds= the CallSeeds that resolve_seeds() or "
            f"check_call() hands back; got {type(seeds).__name__}."
        )
    handed = spec
    compiled = kernel_spec(spec)
    if not isinstance(compiled, ServiceSpec):
        raise TypeError(
            f"resolve_target() takes a ServiceSpec; got {type(compiled).__name__}. A "
            "SelectorSpec's selector is its run: dispatch it."
        )
    spec = compiled
    if spec.many:
        raise ImproperlyConfigured(
            "resolve_target() was handed a many spec, which declares no target selector: its "
            "rows are the call's arguments, and there is no target to find ahead of it."
        )
    target_spec = spec.target_selector_spec()
    parameters = target_spec.parameters() if target_spec is not None else Parameters()
    names = parameters.names()
    scoped = (
        {name: value for name, value in arguments.items() if name in names}
        if isinstance(arguments, Mapping)
        else arguments
    )
    keywords = CheckKeywords({} if call_context is None else call_context)
    checked, granted = open_call(
        spec,
        principal,
        scoped,
        grant=grant,
        pool_seeds=pool_seeds,
        unknown_arguments=UnknownArguments.REJECT,
        parameters=parameters,
        keywords=keywords,
        carried=seeds,
    )
    resolved = walk_target(
        spec, principal, checked, grant=granted, pool_seeds=pool_seeds, keywords=keywords
    )
    if isinstance(resolved, DispatchResult):
        return resolved
    return ResolvedTarget(
        next(iter(resolved.values()), None),
        Grant(spec, principal, target_checked=True),
        CallSeeds(handed, principal, keywords.call_context, pool_seeds, keywords.seeds),
    )
