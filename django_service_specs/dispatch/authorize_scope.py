"""``authorize_scope`` - the object-level check dispatch runs on a set, or on nothing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.utils import (
    SCOPE_LEVEL,
    asked_with,
    offered_seeds,
    offered_to_checks,
    sync_answer,
)
from django_service_specs.dispatch.grant import Grant
from django_service_specs.pool.pool_seeds import PoolSeeds
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
    seeds: Mapping[str, Any] | None = None,
    pool_seeds: PoolSeeds | None = None,
) -> None:
    """Run ``spec``'s scope-level permission checks against ``scope``.

    The counterpart of
    [`authorize_target`][django_service_specs.dispatch.authorize_target.authorize_target]
    for a call that resolves no single row: ``scope`` is the resolved set of a
    bulk or collection call, or ``None`` for a create. Every check's
    ``has_scope_permission`` must pass, in order, and the first refusal raises
    [`NotPermitted`][django_service_specs.authorization.not_permitted.NotPermitted]
    with that check's own message. An answer still to be awaited raises
    ``ImproperlyConfigured`` rather than being read as a pass. A
    [`SpecSource`][django_service_specs.specs.spec_source.SpecSource] is
    checked as the spec it compiles to.

    ``grant.target_checked`` skips the checks here as it does there: a
    transport that already ran the target-level checks has claimed them.
    Dispatch honours it, as there, only for a service spec's target handed
    in as ``target=``, so never on the list a selector spec reads.

    ``arguments`` is handed to each check's method that declares a keyword
    of that name, and to no other, so a check that declares none is asked
    without it. Dispatch passes the call's
    shape-checked arguments as a read-only mapping, whose values are the
    call's own and must not be mutated; ``None`` when the caller has none to
    hand.

    ``call_context`` and ``seeds`` are offered the same way, by name: a
    method declaring ``call_context`` is handed the call's context - the dict
    the transport handed dispatch, a fresh one when it handed none or this is
    called without one - and a method naming a registered seed is handed that
    seed's value from ``seeds``, which dispatch resolves for the call only
    when one of the spec's checks names one. A parameter the call fills by
    position is never read as an opt-in, whatever its name.

    ``pool_seeds`` is for a transport that calls this itself and has the
    registry rather than the values: the
    [`PoolSeeds`][django_service_specs.pool.pool_seeds.PoolSeeds] it would
    hand dispatch. Only the registered seeds a check's ``has_scope_permission`` names
    are resolved, once, for ``principal`` as ``user``, and offered as
    ``seeds`` would be; a seed only another question names, or one no check
    names, is never resolved, and nothing is when ``grant.target_checked`` answers
    first. A resolver raising - ``PrincipalUnavailable`` for one - ends the
    call before any check is asked, as in dispatch. Handing ``seeds`` too
    raises ``TypeError``, since one would silently outrank the other.
    """
    spec = kernel_spec(spec)
    if grant.target_checked:
        return
    # After ``target_checked`` has answered, so a call it answers resolves no seed
    # (test_a_grant_that_checked_the_target_resolves_no_seed).
    offered = offered_to_checks(
        call_context,
        offered_seeds(
            spec,
            principal,
            seeds=seeds,
            pool_seeds=pool_seeds,
            question=SCOPE_LEVEL,
            asked="authorize_scope",
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
            raise NotPermitted(check.message)
