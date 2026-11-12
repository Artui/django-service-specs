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
    """Find and check ``spec``'s target as ``dispatch`` would, without running anything else.

    For a page that shows the row before the call acts on it - the form in
    front of an update, the confirmation in front of a delete - and so must
    show the row dispatch would find, refused where dispatch would refuse.
    It runs dispatch's own steps, in dispatch's order, and the walk after
    them is the very function ``dispatch`` runs:

    1. A deactivated principal is refused, as ``PrincipalUnavailable``.
    2. The shape check over the **target selector's parameters alone**, on
       only the arguments they name. A Validator field is neither required
       nor an unknown key here, so a GET carrying the route's arguments and a
       POST carrying the whole form both resolve; the target's own reads are
       required as declared, except one its ``kwargs`` provider fills or may
       fill, which the lookup's pool must then hold once the provider has
       answered, as at dispatch. A ``reflected`` target read a registered
       seed is named like is no argument, and the seed fills it.
    3. Class-level authorization, honouring ``grant`` as dispatch does. Like
       the two steps before it, before any query.
    4. The lookup, and the checks on what it finds: ``has_object_permission``
       on a row, and ``has_scope_permission`` on a collection target's set,
       empty or not, and on ``None`` - a create, which resolves nothing, and
       a missing row the instance selector's ``allow_none`` lets through.

    Returns ``(target, grant)``, a
    [`ResolvedTarget`][django_service_specs.dispatch.resolved_target.ResolvedTarget]:
    the row, the set, or ``None``, and a grant
    covering ``spec`` and ``principal`` with ``target_checked`` set, which
    is what ``dispatch(spec, ..., target=target, grant=grant)`` takes. So a
    call resolved here looks nothing up again and asks no object-level or
    scope check twice. Its ``.seeds`` are the values every check here was
    offered of each registered seed one names; handed on as
    ``dispatch(..., seeds=found.seeds)``, the run takes them as they are and
    resolves none of them again
    (test_resolve_target_then_dispatch_resolves_it_once). Like the grant they
    are bound to this call, ``call_context`` included: pass dispatch the dict
    passed here. The grant vouches for that target alone: handed to
    dispatch without ``target=``, it covers the class-level check and nothing
    else, and dispatch checks the row its own lookup finds. A
    ``target_checked`` grant handed *in* here is read the same way, since
    this function looks its target up itself. A missing row ``allow_none`` does not let through
    returns ``DispatchResult(kind="not_found")``, dispatch's own answer, so it
    is never mistaken for the ``None`` it lets through.

    ``seeds`` is a carrier of values already resolved for this call: the
    [`CallSeeds`][django_service_specs.dispatch.call_seeds.CallSeeds] that
    [`resolve_seeds`][django_service_specs.dispatch.resolve_seeds.resolve_seeds]
    returns, for a page that ran ``authorize(seeds=)`` before it resolved the
    row, or ``check_call``'s ``.seeds``. Its values stand in for resolving
    the seeds a check names, so the class-level check, the object or scope
    check and the ``.seeds`` handed back carry one value of each, resolved
    nowhere here (test_a_carrier_s_seeds_are_taken_and_resolved_nowhere_else).
    It needs no ``grant``: without one the class-level check is asked on its
    values. One that does not cover this spec, principal, ``call_context``
    dict and ``pool_seeds`` registry is refused as ``NotPermitted`` before any
    resolver runs and before any check is asked; pass the dict the carrier
    was bound to, ``seeds.call_context``.

    ``call_context`` is the call's context, as ``dispatch`` takes it: the
    transport's dict, handed as the same object to the target selector and to
    every permission check method naming it, or a fresh dict of their own when
    none is passed. A check naming a registered seed is offered it here as at
    dispatch, at the class-level check and at the checks on what the lookup
    finds. A page resolving its row ahead of the call passes the dict it will
    hand that call, so the two read and write one context.

    It is sync, as dispatch's steps are; an async caller hops once, with
    ``sync_to_async(resolve_target, thread_sensitive=True)``.

    Raises:
        PrincipalUnavailable: a deactivated principal.
        InvalidArguments: a target read the arguments leave out or get wrong.
        NotPermitted: the class-level, object-level or scope check, or
            ``seeds`` that do not cover this call.
        ImproperlyConfigured: as ``dispatch``, for a spec declaring no
            permissions or a parameter a registered seed occupies that is
            neither a ``reflected`` read nor a top-level Validator field,
            though this checks no Validator field's value.
        ImproperlyConfigured: also a ``many`` spec, which declares no lookup:
            its rows are the call's arguments, and none is found ahead of it.
        TypeError: a ``SelectorSpec``, whose selector is its run rather than
            a lookup in front of one.
        TypeError: ``seeds`` that are anything but a ``CallSeeds``.
    """
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
