"""``resolve_target`` - the target a service spec's dispatch would act on, found ahead of it."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.grant import Grant
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.utils import open_call, walk_target
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.validation.unknown_arguments import UnknownArguments


def resolve_target(
    spec: ServiceSpec,
    *,
    principal: Any,
    arguments: Mapping[str, Any],
    grant: Grant | None = None,
    pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS,
) -> tuple[Any, Grant] | DispatchResult:
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
       required as declared, except one its ``kwargs`` provider is annotated
       to fill.
    3. Class-level authorization, honouring ``grant`` as dispatch does. Like
       the two steps before it, before any query.
    4. The lookup, and the checks on what it finds: ``has_object_permission``
       on a row, and ``has_scope_permission`` on a collection target's set,
       empty or not, and on ``None`` - a create, which resolves nothing, and
       a missing row the instance selector's ``allow_none`` lets through.

    Returns ``(target, grant)``: the row, the set, or ``None``, and a grant
    covering ``spec`` and ``principal`` with ``target_checked`` set, which
    is what ``dispatch(spec, ..., target=target, grant=grant)`` takes. So a
    call resolved here looks nothing up again and asks no object-level or
    scope check twice. The grant vouches for that target alone: handed to
    dispatch without ``target=``, it covers the class-level check and nothing
    else, and dispatch checks the row its own lookup finds. A
    ``target_checked`` grant handed *in* here is read the same way, since
    this function looks its target up itself. A missing row ``allow_none`` does not let through
    returns ``DispatchResult(kind="not_found")``, dispatch's own answer, so it
    is never mistaken for the ``None`` it lets through.

    It is sync, as dispatch's steps are; an async caller hops once, with
    ``sync_to_async(resolve_target, thread_sensitive=True)``.

    Raises:
        PrincipalUnavailable: a deactivated principal.
        InvalidArguments: a target read the arguments leave out or get wrong.
        NotPermitted: the class-level, object-level or scope check.
        ImproperlyConfigured: as ``dispatch``, for a spec declaring no
            permissions or any parameter a registered seed occupies - a
            Validator field too, though this checks no Validator field's
            value.
        ImproperlyConfigured: also a ``many`` spec, which declares no lookup:
            its rows are the call's arguments, and none is found ahead of it.
        TypeError: a ``SelectorSpec``, whose selector is its run rather than
            a lookup in front of one.
    """
    if not isinstance(spec, ServiceSpec):
        raise TypeError(
            f"resolve_target() takes a ServiceSpec; got {type(spec).__name__}. A "
            "SelectorSpec's selector is its run: dispatch it."
        )
    if spec.many:
        raise ImproperlyConfigured(
            "resolve_target() was handed a many spec, which declares no target selector: its "
            "rows are the call's arguments, and there is no target to find ahead of it."
        )
    target_spec = spec.target_selector_spec()
    parameters = target_spec.parameters() if target_spec is not None else Parameters()
    names = parameters.names()
    # Arguments that are no mapping go to the shape check whole, which refuses
    # them as dispatch does: test_arguments_that_are_no_mapping_are_refused_by_the_shape_check.
    scoped = (
        {name: value for name, value in arguments.items() if name in names}
        if isinstance(arguments, Mapping)
        else arguments
    )
    checked, granted = open_call(
        spec,
        principal,
        scoped,
        grant=grant,
        pool_seeds=pool_seeds,
        unknown_arguments=UnknownArguments.REJECT,
        parameters=parameters,
    )
    resolved = walk_target(spec, principal, checked, grant=granted, pool_seeds=pool_seeds)
    if isinstance(resolved, DispatchResult):
        return resolved
    return next(iter(resolved.values()), None), Grant(spec, principal, target_checked=True)
