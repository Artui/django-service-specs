"""``authorize_target`` - the object-level check dispatch runs on a resolved row."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.utils import (
    OBJECT_LEVEL,
    asked_with,
    check_seed_arguments,
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


def authorize_target(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    principal: Any,
    target: Any,
    *,
    grant: Grant,
    arguments: Mapping[str, Any] | None = None,
    call_context: dict[str, Any] | None = None,
    seeds: Mapping[str, Any] | None = None,
    pool_seeds: PoolSeeds | None = None,
) -> None:
    """Run ``spec``'s object-level permission checks against a resolved ``target``.

    Dispatch calls this on a retrieved row, never on a list: a collection has
    no single object to check against, and a member-level rule belongs to the
    presenter or the query that shaped it.

    ``grant.target_checked`` lets a transport that resolved the row itself and
    already ran the object-level check claim it once, so dispatch does not pay
    for it twice; dispatch honours it only for a service spec's target
    handed in as ``target=``, and never on a selector spec's row (see
    ``Grant``); otherwise every check's ``has_object_permission`` must pass,
    in order, and the first refusal raises
    [`NotPermitted`][django_service_specs.authorization.not_permitted.NotPermitted]
    with that check's own message. An answer still to be awaited raises
    ``ImproperlyConfigured`` rather than being read as a pass. A
    [`SpecSource`][django_service_specs.specs.spec_source.SpecSource] is
    checked as the spec it compiles to.

    ``spec.permissions is None`` means nothing to check here rather than a
    configuration error: [`authorize`][django_service_specs.dispatch.authorize.authorize]
    already refused an undeclared spec before any target could be resolved, so
    this function is never reached with one - iterating an empty tuple in its
    place is simpler than asserting an invariant this module cannot enforce.

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
    hand dispatch. Only the registered seeds a check's ``has_object_permission`` names
    are resolved, once, for ``principal`` as ``user``, and offered as
    ``seeds`` would be; a seed only another question names, or one no check
    names, is never resolved, and nothing is when ``grant.target_checked`` answers
    first. A resolver raising - ``PrincipalUnavailable`` for one - ends the
    call before any check is asked, as in dispatch. Handing ``seeds`` too
    raises ``TypeError``, since one would silently outrank the other, even when
    the call is answered before a check is asked.

    A deactivated ``principal`` handed with ``pool_seeds`` raises
    ``PrincipalUnavailable`` before any seed is resolved, as dispatch refuses
    one before anything else - grant or no grant, so a grant that checked the target
    does not stand in for it. Without ``pool_seeds`` nothing is resolved, and the call
    is asked exactly as before the keyword existed.
    """
    # Ahead of every short cut below, so a call they answer is still refused
    # for both kinds, and for a deactivated principal, as dispatch refuses one
    # grant or no grant (tests: TestPoolSeeds.test_both_kinds_are_refused_*
    # and test_a_deactivated_principal_is_refused_though_*).
    check_seed_arguments(principal, seeds=seeds, pool_seeds=pool_seeds, asked="authorize_target")
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
            question=OBJECT_LEVEL,
            call_context=call_context,
        ),
    )
    for check in spec.permissions or ():
        answer = check.has_object_permission(
            principal,
            spec,
            target,
            **asked_with(check, "has_object_permission", arguments, positional=3, offered=offered),
        )
        if not sync_answer(answer, asked=f"{type(check).__qualname__}.has_object_permission"):
            raise NotPermitted(check.message)
