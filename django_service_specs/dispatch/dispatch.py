"""``dispatch`` - run one operation, from sync code, on any transport."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.authorization.grant import Grant
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.utils import (
    SELECTOR_SOURCE,
    conclude_selector,
    finish_service,
    lookup,
    open_call,
    prepare_service,
    selector_pool,
)
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.services.run_service import run_service
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.progress_reporter import ProgressReporter
from django_service_specs.validation.unknown_arguments import UnknownArguments


def dispatch(
    spec: ServiceSpec | SelectorSpec,
    *,
    principal: Any,
    arguments: Mapping[str, Any],
    grant: Grant | None = None,
    pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS,
    unknown_arguments: UnknownArguments = UnknownArguments.REJECT,
    progress: ProgressReporter | None = None,
) -> DispatchResult:
    """Run ``spec`` for ``principal`` with ``arguments``, in a fixed order.

    First, a deactivated principal is refused as ``PrincipalUnavailable``: an
    authenticated one whose ``is_active`` is false, with or without a
    ``grant``. One with no ``is_active`` reads as active, and anonymous goes on
    to the permission check, which decides whether anonymous may act. It is
    the rule ``resolve_principal`` and the HTTP entry points apply, so a
    principal is refused alike whichever way it reached dispatch.

    Then the same seven steps for both kinds of spec, and for ``adispatch``:

    1. [`check_arguments`][django_service_specs.parameters.check_arguments.check_arguments]
       over ``spec.parameters()`` under ``unknown_arguments``: the closed
       argument set and the shape check. A parameter a registered seed in
       ``pool_seeds`` occupies is refused before that, as a configuration error.
    2. [`authorize`][django_service_specs.authorization.authorize.authorize],
       honouring ``grant`` if it covers this spec and principal. Before anything
       is resolved, so a refused principal learns nothing about which rows exist.
    3. Resolution: a selector spec's own selector, or a service spec's instance
       or collection selector, called with the base pool plus the arguments its
       ``reads`` declare, then shaped, and a RETRIEVE collapsed to its row. A
       missing row is ``DispatchResult(kind="not_found")``, returned rather than
       raised, unless the selector says ``allow_none``.
    4. [`authorize_target`][django_service_specs.authorization.authorize_target.authorize_target]
       on a retrieved row - never on a list, and never on a ``None`` that
       ``allow_none`` let through.
    5. A service spec's Validator, on only the arguments it declares, with the
       resolved target in its context.
    6. A service spec's ``affordances``, through
       [`enforce_affordances`][django_service_specs.affordances.enforce_affordances.enforce_affordances]:
       the first one not met refuses the call as ``ActionUnavailable`` carrying
       its ``code``. After the object-level check, so a principal who may not
       see the row is never told what state it is in, and before the run's
       transaction opens, so a refusal never opens one.
    7. The run: the service, called with the principal, ``data`` (the
       validated values), ``instance`` or ``collection``, each validated value by
       name, ``progress`` and every registered seed, through
       [`run_service`][django_service_specs.services.run_service.run_service] so
       ``spec.atomic`` holds and an ``async def`` service is bridged. Then the
       output selector, if declared, with the service's return as ``result``.

    A selector spec stops after step four: its selector is its run. Its
    ``affordances`` are answers about each row, for a list to report, and
    nothing about reading is refused by them.

    ``progress`` is the transport's own progress reporter, seeded under the
    reserved name ``progress`` into the pool of whatever is this call's run -
    the service, or a selector spec's own selector - and into a callable
    affordance condition's. With none, the pool carries ``null_progress``, so a
    callable that declares the parameter runs on every transport. A target or
    output selector always gets ``null_progress``: a lookup has nothing to
    report, and one reporting after the service finished would read as the
    work restarting.

    ``kind`` is ``"list"`` for a LIST selector spec or a service whose output
    selector is a LIST, and ``"instance"`` otherwise. Nothing is presented here;
    [`present`][django_service_specs.dispatch.present.present] does that, so a
    transport that hands the object to a template never pays for rendering it.

    Raises:
        PrincipalUnavailable: a deactivated principal, before step one.
        InvalidArguments: step one, or the Validator.
        NotPermitted: step two or step four.
        ActionUnavailable: step six, an affordance not met.
        ServiceNotFound: step six, a condition on the row reached after the row
            was deleted.
        ImproperlyConfigured: a spec that declares no permissions, a parameter
            or a validated value named after a seed, shaping declared on a
            selector that returned something other than a queryset, or a
            condition on the row with no row to answer it for.
    """
    if isinstance(spec, SelectorSpec):
        checked, granted = open_call(
            spec,
            principal,
            arguments,
            grant=grant,
            pool_seeds=pool_seeds,
            unknown_arguments=unknown_arguments,
        )
        pool = selector_pool(
            spec, checked, principal=principal, pool_seeds=pool_seeds, progress=progress
        )
        value = lookup(spec, pool, source=SELECTOR_SOURCE)
        return conclude_selector(spec, value, principal=principal, grant=granted)
    prepared = prepare_service(
        spec,
        principal,
        arguments,
        grant=grant,
        pool_seeds=pool_seeds,
        unknown_arguments=unknown_arguments,
        progress=progress,
    )
    if isinstance(prepared, DispatchResult):
        return prepared
    result = run_service(spec.service, prepared.kwargs, atomic=spec.atomic)
    return finish_service(spec, prepared, result, pool_seeds=pool_seeds)
