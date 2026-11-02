"""``resolve_seeds`` - the seeds a spec's checks name, resolved once, ahead of ``authorize``."""

from __future__ import annotations

from typing import Any

from django_service_specs.authorization.utils import (
    QUESTIONS,
    refuse_deactivated,
    seeds_for_checks,
)
from django_service_specs.dispatch.call_seeds import CallSeeds
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource


def resolve_seeds(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    *,
    principal: Any,
    pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS,
    call_context: dict[str, Any] | None = None,
) -> CallSeeds:
    """The registered seeds ``spec``'s checks name, resolved for ``principal``, as a carrier.

    For a transport that admits a call before it resolves the row - a page
    asking the class-level check before it shows a form, then finding the
    row, then running the call. Handed the
    [`CallSeeds`][django_service_specs.dispatch.call_seeds.CallSeeds] this
    returns as ``seeds=``,
    [`authorize`][django_service_specs.dispatch.authorize.authorize],
    [`authorize_scope`][django_service_specs.dispatch.authorize_scope.authorize_scope],
    [`authorize_target`][django_service_specs.dispatch.authorize_target.authorize_target],
    [`resolve_target`][django_service_specs.dispatch.resolve_target.resolve_target]
    and ``dispatch`` all take these values as they are, so the class-level
    check, the object or scope check and the run see one value of each,
    resolved here once (test_one_resolution_from_resolve_seeds_to_dispatch,
    test_one_resolution_on_the_many_path).

    The seeds resolved are those a check of the spec names **at any of its
    three questions** - ``has_permission``, ``has_object_permission`` and
    ``has_scope_permission`` - as dispatch resolves them before its
    class-level check, and as ``check_call`` hands them back. That is wider
    than ``authorize(pool_seeds=)``, which resolves only the seeds the
    class-level question names. A seed no check names stays unresolved: it
    resolves in each of dispatch's pools as it always does
    (test_it_resolves_what_check_call_resolves). Resolved from a base pool
    with ``principal`` as ``user`` and no live reporter; a resolver raising -
    ``PrincipalUnavailable`` for one - ends the call here. A spec declaring
    no permissions resolves nothing, and ``authorize`` refuses it next.

    A deactivated ``principal`` is refused first, as ``PrincipalUnavailable``,
    before any seed resolves, as dispatch refuses one
    (test_a_deactivated_principal_resolves_no_seed).

    The carrier is bound by identity to ``spec`` as handed (compared as
    compiled, so a carrier for a
    [`SpecSource`][django_service_specs.specs.spec_source.SpecSource] covers
    the spec it compiles to), to ``principal``, to the ``call_context`` dict
    and to the ``pool_seeds`` registry, and every function that takes it
    refuses one that does not cover its call as ``NotPermitted``. Handed no
    ``call_context``, it is bound to a fresh dict, readable as
    ``.call_context``
    (test_a_call_handed_no_context_gets_a_dict_readable_on_the_carrier).
    **The common mistake** is then to hand ``authorize(seeds=carrier)`` no
    ``call_context`` either: ``None`` is not that dict, so the call is
    refused. Pass ``call_context=carrier.call_context`` to every step, or
    hand this the dict the call will use
    (test_authorize_without_the_carrier_s_context_is_refused).
    Like a grant, the carrier cannot be pickled.

    Raises:
        PrincipalUnavailable: a deactivated principal, or a resolver
            raising it.
    """
    refuse_deactivated(principal)
    context = {} if call_context is None else call_context
    values = seeds_for_checks(
        kernel_spec(spec), principal, pool_seeds, QUESTIONS, call_context=context
    )
    # Bound to ``spec`` as handed, as ``check_call`` binds its carrier: ``covers``
    # compiles it (test_a_carrier_for_a_source_is_bound_to_the_source).
    return CallSeeds(spec, principal, context, pool_seeds, values)
