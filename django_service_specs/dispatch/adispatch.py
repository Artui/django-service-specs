from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from asgiref.sync import sync_to_async
from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404

from django_service_specs.authorization.resolve_principal import resolve_principal
from django_service_specs.dispatch.call_seeds import CallSeeds
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.grant import Grant
from django_service_specs.dispatch.utils import (
    NOT_FOUND,
    SELECTOR_SOURCE,
    CheckKeywords,
    Overlay,
    Prepared,
    conclude_selector,
    finish_service,
    open_call,
    prepare_service,
    refuse_seeds,
    refuse_target,
    reraise_unless_retrieve,
    selector_pool,
    settle,
    shapes_sent,
    with_run_progress,
)
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.selectors.utils import call_keywords
from django_service_specs.services.arun_service import arun_service
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.types.is_async import is_async
from django_service_specs.types.progress_reporter import ProgressReporter
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.types.unknown_arguments import UnknownArguments
from django_service_specs.types.unset import UNSET


async def adispatch(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    *,
    principal: Any = None,
    principal_id: Any = None,
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
    """Run ``spec`` from async code: ``dispatch``'s steps, order and refusals."""
    if (principal is None) == (principal_id is None):
        raise TypeError("adispatch() takes exactly one of principal= and principal_id=.")
    spec = kernel_spec(spec)
    refuse_target(spec, target)
    refuse_seeds(seeds, grant, principal_id=principal_id)
    overlay = Overlay(dict(extra_kwargs or {}))
    if call_context is None:
        call_context = {}
    rest = (
        principal,
        principal_id,
        arguments,
        grant,
        pool_seeds,
        unknown_arguments,
        progress,
        overlay,
        call_context,
        seeds,
    )
    if isinstance(spec, SelectorSpec):
        if is_async(spec.selector):
            return await _await_selector(spec, *rest)
    elif is_async(spec.service) and not spec.atomic:
        return await _await_service(spec, *rest, target)
    return await sync_to_async(_dispatch, thread_sensitive=True)(spec, *rest, target)


def _principal(principal: Any, principal_id: Any) -> Any:
    return resolve_principal(principal_id) if principal is None else principal


def _dispatch(
    spec: ServiceSpec | SelectorSpec,
    principal: Any,
    principal_id: Any,
    arguments: Mapping[str, Any],
    grant: Grant | None,
    pool_seeds: PoolSeeds,
    unknown_arguments: UnknownArguments,
    progress: ProgressReporter | None,
    overlay: Overlay,
    call_context: dict[str, Any],
    seeds: CallSeeds | None,
    target: Any,
) -> DispatchResult:
    """The whole of ``dispatch``, the principal resolved first: the one-hop case."""
    return dispatch(
        spec,
        principal=_principal(principal, principal_id),
        arguments=arguments,
        grant=grant,
        pool_seeds=pool_seeds,
        unknown_arguments=unknown_arguments,
        progress=progress,
        target=target,
        extra_kwargs=overlay.kwargs,
        call_context=call_context,
        seeds=seeds,
    )


def _prepare(
    spec: ServiceSpec,
    principal: Any,
    principal_id: Any,
    arguments: Mapping[str, Any],
    grant: Grant | None,
    pool_seeds: PoolSeeds,
    unknown_arguments: UnknownArguments,
    progress: ProgressReporter | None,
    overlay: Overlay,
    call_context: dict[str, Any],
    seeds: CallSeeds | None,
    target: Any,
) -> Prepared | DispatchResult:
    return prepare_service(
        spec,
        _principal(principal, principal_id),
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


async def _await_service(
    spec: ServiceSpec,
    principal: Any,
    principal_id: Any,
    arguments: Mapping[str, Any],
    grant: Grant | None,
    pool_seeds: PoolSeeds,
    unknown_arguments: UnknownArguments,
    progress: ProgressReporter | None,
    overlay: Overlay,
    call_context: dict[str, Any],
    seeds: CallSeeds | None,
    target: Any,
) -> DispatchResult:
    """A non-atomic async service: its prelude hop, the await, the output hop."""
    prepared = await sync_to_async(_prepare, thread_sensitive=True)(
        spec,
        principal,
        principal_id,
        arguments,
        grant,
        pool_seeds,
        unknown_arguments,
        progress,
        overlay,
        call_context,
        seeds,
        target,
    )
    if isinstance(prepared, DispatchResult):
        return prepared
    result = await arun_service(spec.service, prepared.kwargs, atomic=False)
    if spec.output_selector_spec is None:
        return finish_service(spec, prepared, result, pool_seeds=pool_seeds)
    return await sync_to_async(finish_service, thread_sensitive=True)(
        spec, prepared, result, pool_seeds=pool_seeds
    )


def _open_selector(
    spec: SelectorSpec,
    principal: Any,
    principal_id: Any,
    arguments: Mapping[str, Any],
    grant: Grant | None,
    pool_seeds: PoolSeeds,
    unknown_arguments: UnknownArguments,
    progress: ProgressReporter | None,
    overlay: Overlay,
    call_context: dict[str, Any],
    seeds: CallSeeds | None,
) -> tuple[Any, Grant, dict[str, Any], dict[str, Any], dict[str, Any], CheckKeywords]:
    """Steps one and two, the selector's pool, and its keywords, in the one sync hop."""
    who = _principal(principal, principal_id)
    keywords = CheckKeywords(call_context)
    checked, granted = open_call(
        spec,
        who,
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
        principal=who,
        pool_seeds=pool_seeds,
        keywords=keywords,
        shapes=shapes_sent(spec, checked),
        progress=progress,
        extra_kwargs=overlay.kwargs,
    )
    kwargs = with_run_progress(
        spec,
        call_keywords(spec.selector, pool, fillable=spec.reads.names()),
        pool,
        reserved=pool_seeds.reserved,
        transport=progress,
    )
    return who, granted, pool, kwargs, checked, keywords


def _settle_and_conclude(
    spec: SelectorSpec,
    raw: Any,
    pool: dict[str, Any],
    who: Any,
    granted: Grant,
    reserved: frozenset[str],
    checked: dict[str, Any],
    keywords: CheckKeywords,
) -> DispatchResult:
    value = settle(
        spec, raw, pool, source=SELECTOR_SOURCE, reserved=reserved, fillable=spec.reads.names()
    )
    return conclude_selector(
        spec,
        value,
        principal=who,
        grant=granted,
        pool=pool,
        reserved=reserved,
        checked=checked,
        keywords=keywords,
    )


async def _await_selector(
    spec: SelectorSpec,
    principal: Any,
    principal_id: Any,
    arguments: Mapping[str, Any],
    grant: Grant | None,
    pool_seeds: PoolSeeds,
    unknown_arguments: UnknownArguments,
    progress: ProgressReporter | None,
    overlay: Overlay,
    call_context: dict[str, Any],
    seeds: CallSeeds | None,
) -> DispatchResult:
    """An ``async def`` selector spec: steps one and two, the await, then shaping and step four."""
    who, granted, pool, kwargs, checked, keywords = await sync_to_async(
        _open_selector, thread_sensitive=True
    )(
        spec,
        principal,
        principal_id,
        arguments,
        grant,
        pool_seeds,
        unknown_arguments,
        progress,
        overlay,
        call_context,
        seeds,
    )
    try:
        raw = await spec.selector(**kwargs)
    except (ObjectDoesNotExist, Http404) as error:
        if isinstance(error, Http404) and spec.kind is SelectorKind.LIST:
            return NOT_FOUND
        reraise_unless_retrieve(spec, error)
        return conclude_selector(
            spec,
            None,
            principal=who,
            grant=granted,
            pool=pool,
            reserved=pool_seeds.reserved,
            checked=checked,
            keywords=keywords,
        )
    return await sync_to_async(_settle_and_conclude, thread_sensitive=True)(
        spec, raw, pool, who, granted, pool_seeds.reserved, checked, keywords
    )
