from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.dispatch.call_seeds import CallSeeds
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.grant import Grant
from django_service_specs.dispatch.utils import (
    NOT_FOUND,
    SELECTOR_SOURCE,
    CheckKeywords,
    ListNotFound,
    Overlay,
    conclude_selector,
    finish_service,
    lookup,
    open_call,
    prepare_service,
    refuse_seeds,
    refuse_target,
    selector_pool,
    shapes_sent,
)
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.services.run_service import run_service
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.types.progress_reporter import ProgressReporter
from django_service_specs.types.unknown_arguments import UnknownArguments
from django_service_specs.types.unset import UNSET


def dispatch(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    *,
    principal: Any,
    arguments: Mapping[str, Any],
    grant: Grant | None = None,
    seeds: CallSeeds | None = None,
    pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS,
    unknown_arguments: UnknownArguments = UnknownArguments.REJECT,
    progress: ProgressReporter | None = None,
    target: Any = UNSET,
    extra_kwargs: Mapping[str, Any] | None = None,
    call_context: dict[str, Any] | None = None,
) -> DispatchResult:
    """Run ``spec`` for ``principal`` with ``arguments``, in a fixed order."""
    spec = kernel_spec(spec)
    refuse_target(spec, target)
    refuse_seeds(seeds, grant)
    overlay = Overlay(dict(extra_kwargs or {}))
    if call_context is None:
        call_context = {}
    if isinstance(spec, SelectorSpec):
        keywords = CheckKeywords(call_context)
        checked, granted = open_call(
            spec,
            principal,
            arguments,
            grant=grant,
            pool_seeds=pool_seeds,
            unknown_arguments=unknown_arguments,
            overlay=overlay,
            keywords=keywords,
            carried=seeds,
        )
        pool = selector_pool(
            spec,
            checked,
            principal=principal,
            pool_seeds=pool_seeds,
            keywords=keywords,
            shapes=shapes_sent(spec, checked),
            progress=progress,
            extra_kwargs=overlay.kwargs,
        )
        try:
            value = lookup(
                spec,
                pool,
                source=SELECTOR_SOURCE,
                reserved=pool_seeds.reserved,
                run=True,
                transport=progress,
            )
        except ListNotFound:
            return NOT_FOUND
        return conclude_selector(
            spec,
            value,
            principal=principal,
            grant=granted,
            pool=pool,
            reserved=pool_seeds.reserved,
            checked=checked,
            keywords=keywords,
        )
    prepared = prepare_service(
        spec,
        principal,
        arguments,
        grant=grant,
        pool_seeds=pool_seeds,
        unknown_arguments=unknown_arguments,
        progress=progress,
        call_context=call_context,
        carried=seeds,
        target=target,
        overlay=overlay,
    )
    if isinstance(prepared, DispatchResult):
        return prepared
    result = run_service(spec.service, prepared.kwargs, atomic=spec.atomic)
    return finish_service(spec, prepared, result, pool_seeds=pool_seeds)
