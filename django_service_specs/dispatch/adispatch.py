"""``adispatch`` - run one operation from async code, in ``dispatch``'s order."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from asgiref.sync import sync_to_async
from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404

from django_service_specs.authorization.resolve_principal import resolve_principal
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
    refuse_target,
    reraise_unless_retrieve,
    selector_pool,
    settle,
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
    pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS,
    unknown_arguments: UnknownArguments = UnknownArguments.REJECT,
    progress: ProgressReporter | None = None,
    target: Any = UNSET,
    extra_kwargs: Mapping[str, Any] | None = None,
    call_context: dict[str, Any] | None = None,
) -> DispatchResult:
    """Run ``spec`` from async code: ``dispatch``'s steps, order and refusals.

    **Every concept is sync-only**, and so is every spec-carried callable but
    one. A permission check, a Validator, a selector nested in a service spec,
    ``extend_queryset``, a seed's resolver, a spec's providers and its
    preconditions may each query, so each runs in
    Django's thread-sensitive executor, never on the event loop. Only the run
    may be ``async def`` - the service, or a selector spec's own selector -
    because it is the one callable no phase shares: a spec is written once for
    both entry points, and a concept written ``async def`` could not be called
    from ``dispatch``.

    So the phases run in **one** ``sync_to_async(thread_sensitive=True)`` hop,
    and the run's shape decides only what else joins it:

    Every refusal before the run is made inside that hop, an affordance and
    a service spec's precondition included: a condition on the row is a
    query. A selector spec's preconditions run on what its selector found,
    so after an ``async def`` one they join the hop that shapes its return.

    - A sync run joins the hop, so a sync spec costs exactly one.
    - An atomic ``async def`` service joins it too, through the bridge in
      [`run_service`][django_service_specs.services.run_service.run_service]:
      ``transaction.atomic`` is sync-only, so the transaction is opened on the
      executor thread and the coroutine is driven from inside it, where its own
      thread-sensitive ORM calls come back to the connection holding it.
    - A non-atomic ``async def`` run is awaited on the loop after the hop.
      Holding the executor thread while it awaits - a network call, say -
      would stall every thread-sensitive call queued behind it. What follows it
      (an output selector; a selector spec's shaping, row and object-level
      check) takes a second hop, and only when there is such a thing to do.

    Exactly one of ``principal`` and ``principal_id``. ``principal_id`` is
    resolved with
    [`resolve_principal`][django_service_specs.authorization.resolve_principal.resolve_principal]
    inside the hop, because resolving it is itself a query; taking only the
    row would push that query into a hop of the caller's. A ``grant`` never
    covers a principal resolved here, since a grant is bound to the principal
    object it was minted for. A deactivated row is refused there, with its
    identifier in the message; a deactivated ``principal`` is refused by
    ``dispatch``'s own check, which reads the same rule, so the two cannot
    disagree about who may act.

    ``progress`` reaches the run as it does under ``dispatch``, including an
    ``async def`` one awaited on the loop, so a reporter must be safe to call
    from either: the executor thread for a sync run, and an event loop for an
    ``async def`` one, atomic or not. A spec's ``progress_reporter`` is never
    called on the loop: for an ``async def`` run it is resolved inside the
    hop, once nothing before the run can refuse the call.

    ``target`` is ``dispatch``'s: a service spec's target the caller resolved,
    standing in for the lookup inside the one hop, and checked there unless
    ``grant`` says ``target_checked``; without ``target``, checked whatever
    the grant says. A selector spec and a ``many`` spec
    refuse it before any hop, and a selector spec's row or list is checked
    whatever the grant says, as ``dispatch``'s is.

    ``extra_kwargs`` is ``dispatch``'s overlay, copied on entry, merged
    beneath the spec's ``kwargs`` provider inside the hop, on every path, and
    refused there where it names a declared parameter; beneath the
    Validator's computed and bound values too, as in ``dispatch``, on both
    hops (test_a_value_the_validator_computed_outranks_the_overlay_on_both_hops).
    That refusal and the read of whether a check declares ``arguments`` both run off the loop
    (test_the_overlay_refusal_and_a_check_s_signature_are_read_off_the_loop).

    ``call_context`` is ``dispatch``'s: the transport's dict, handed to every
    stage that declares it as the same object, on every path and across
    every hop; with none, one fresh dict for the call, made here on entry, so
    the stages of each hop share it.

    A ``many`` spec checks, validates and writes its rows as ``dispatch``
    does, every row inside the one hop.

    Raises:
        TypeError: both or neither of ``principal`` and ``principal_id``;
            ``target`` where ``dispatch`` refuses it.
        PrincipalUnavailable: ``principal_id`` names no principal who may act,
            or ``principal`` is deactivated.
        InvalidArguments, NotPermitted, ImproperlyConfigured: as ``dispatch``.
        ActionUnavailable, ServiceNotFound: as ``dispatch``, from its affordances.
    """
    # One branch to coverage, so each side is held by its own test besides
    # test_exactly_one_of_principal_and_principal_id_is_required: the first by
    # test_a_sync_selector_spec_costs_one_hop (``principal`` alone), the second
    # by test_principal_id_is_resolved_inside_the_one_hop (``principal_id`` alone).
    if (principal is None) == (principal_id is None):
        raise TypeError("adispatch() takes exactly one of principal= and principal_id=.")
    # Compiled on the loop, before the branch that reads which kind of spec it is.
    spec = kernel_spec(spec)
    refuse_target(spec, target)
    # Copied here, on the loop, so a caller changing its dict while the call
    # is in a hop changes nothing the run sees
    # (test_extra_kwargs_are_copied_on_entry_so_a_change_during_the_call_reaches_nothing).
    overlay = Overlay(dict(extra_kwargs or {}))
    # Made once, here, and never again by ``dispatch``: every hop is handed
    # this one object (test_a_call_handed_none_gets_a_fresh_dict_its_stages_share).
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
    )
    if isinstance(spec, SelectorSpec):
        if is_async(spec.selector):
            return await _await_selector(spec, *rest)
    elif is_async(spec.service) and not spec.atomic:
        # One branch to coverage, so each condition is held by its own test:
        # test_a_non_atomic_sync_service_costs_one_hop (the first) and
        # test_an_atomic_async_service_joins_the_hop_and_rolls_back (the second).
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
    target: Any,
) -> DispatchResult:
    """A non-atomic ``async def`` service: the prelude's hop, the await, then the output selector's."""
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
        target,
    )
    if isinstance(prepared, DispatchResult):
        return prepared
    # ``atomic=False`` because this path is only reached for a spec that says
    # so; an atomic one joined the prelude's hop instead.
    result = await arun_service(spec.service, prepared.kwargs, atomic=False)
    if spec.output_selector_spec is None:
        # Nothing left that queries: building the result is plain data, so it
        # costs no second hop.
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
) -> tuple[Any, Grant, dict[str, Any], dict[str, Any], dict[str, Any], CheckKeywords]:
    """Steps one and two, the selector's pool, and its keywords, in the one sync hop.

    The keywords are bound here, a read the caller left out refused as on
    every other path, and the run's reporter joined to them after that: its
    provider may query, so it is resolved here rather than on the loop.
    """
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
    )
    pool = selector_pool(
        spec,
        checked,
        principal=who,
        pool_seeds=pool_seeds,
        call_context=call_context,
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
) -> DispatchResult:
    """An ``async def`` selector spec: steps one and two, the await, then shaping and step four.

    The selector is the spec's run and has no ``atomic``, so it is awaited on
    the loop like any non-atomic async run. What it returns is usually a
    queryset nobody has evaluated yet; shaping it may call ``extend_queryset``,
    and collapsing a RETRIEVE to its row is a query, so both go back to the
    executor, with the object-level check.
    """
    # Bound before the await and outside the ``try``: a read the caller left
    # out is refused as a missing argument, as on every other path.
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
    )
    try:
        raw = await spec.selector(**kwargs)
    except (ObjectDoesNotExist, Http404) as error:
        # As ``lookup`` maps them, with a LIST's ``Http404`` answered here as
        # sync ``dispatch`` answers it. Each member and conjunct is held by its
        # own test: test_an_async_selector_spec_raising_does_not_exist_runs_no_precondition
        # (``ObjectDoesNotExist``), the ``required`` case of
        # test_an_async_retrieve_raising_http404_is_not_found_or_none_under_allow_none
        # (``Http404``), test_an_async_list_raising_does_not_exist_passes_through
        # (the ``isinstance``) and that test's ``allow-none`` case (the kind).
        if isinstance(error, Http404) and spec.kind is SelectorKind.LIST:
            return NOT_FOUND
        reraise_unless_retrieve(spec, error)
        # No row, so no object-level check and nothing that queries: the
        # not-found (or ``allow_none``'s ``None``) is decided without a hop.
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
