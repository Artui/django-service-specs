"""``check_seeds`` - a declaration that cannot hold on a mount as written, refused before any call."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.dispatch.utils import (
    COLLECTION_SOURCE,
    EVERY_POOL,
    INSTANCE_SOURCE,
    SELECTOR_SOURCE,
    seed_named_refusal,
    split_seed_named,
    target_entry,
)
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.pool.provider_keys import provider_keys
from django_service_specs.selectors.utils import required_keywords
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.types.unset import UNSET

_SERVICE_SOURCE: Final = "ServiceSpec.service"


def check_seeds(
    spec: ServiceSpec | SelectorSpec | SpecSource, *, pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS
) -> None:
    """Refuse a declaration that cannot hold as written on a mount registering ``pool_seeds``.

    Four of them, below: a parameter a seed or the call's own value would
    meet, a positional-only parameter dispatch cannot pass, a keyword nothing
    fills, and an optional read over a keyword that requires it. The first
    fails every call, the second and third every call that reaches the
    callable, and the fourth every call leaving the read out, which the
    declaration says a caller may. Each is decided by the spec and the
    mount's registered seeds alone, so a transport registering a kernel spec
    can refuse it where it registers it rather than list a tool or a route
    whose calls fail in a way the declaration already settled. The spec does
    not refuse these itself when it is built because the seeds are the
    mount's, and a keyword one mount fills is unfilled on another. Nothing
    runs: no seed resolves, no provider is called and no query is made.
    Every refusal it finds is named in one ``ImproperlyConfigured``, each
    offender in a sorted list such as ``['tenant']``.

    1. **A parameter a registered seed is named like**, or ``request`` or
       ``view``, that dispatch refuses on every call: a read nobody marked
       ``reflected``, a shape, a ``many`` spec's list
       ([`seed_named_parameters`][django_service_specs.dispatch.seed_named_parameters.seed_named_parameters]'s
       second set), in the words dispatch refuses it in. A selector spec's
       own read or shape of either call name is one, refused here and by
       dispatch rather than when it is built.
    2. **A positional-only parameter with no default**, of the service, the
       selector or the target selector. Dispatch calls each by keyword, so
       nothing fills one, a read of its name included.
    3. **A keyword the callable requires that nothing fills**: by name, with
       no default, and in none of the places dispatch fills a keyword from
       - what every pool carries (``user``, ``progress``, ``call_context``,
       ``shapes``, ``request``, ``view``), a seed ``pool_seeds`` registers,
       a read of the callable's own seat, a key the seat's typed ``kwargs``
       provider names, and for a service ``data``, and ``instance`` or
       ``collection`` where a target selector resolves one. The kernel
       seeds ``data`` for a service only, so a selector requiring it is
       refused as any unfilled keyword is. A service is handed its spec's
       reads, never its target selector's or its shapes, which reach it as
       ``shapes``.
    4. **A keyword the callable requires that only an optional read fills**:
       a read the shape check does not demand - declared ``required=False``,
       or declaring a ``default``, which is reported and never applied - over
       a keyword with no default, that no seed and no provider fills. A call
       sending it runs, and one leaving it out is refused as missing
       (``call_keywords``), so a caller reading the declaration is told the
       read is optional and refused for omitting it.

    **A callable whose signature cannot be read** is refused too, ahead of
    these for its seat: a service, selector or target selector such as a
    builtin type like ``dict``, which dispatch cannot bind a keyword to and so
    fails on for every call reaching it. The second to fourth need that
    signature, so such a seat is answered by this refusal alone, and the
    other seats are still checked.

    A Validator field the service never receives is not among them, because
    such a spec runs and may mean to: [`unreceived_fields`][django_service_specs.dispatch.unreceived_fields.unreceived_fields]
    answers it, and the transport decides.

    **What it cannot see, and so never refuses.** A provider whose return
    says nothing about its keys may fill any keyword in its seat, so that
    seat's keywords are left to dispatch (the third and fourth). A
    Validator may return a value it does not declare, or bind one, so a
    service beside a Validator is not judged by the third and fourth either
    (test_a_service_beside_a_validator_is_left_to_dispatch). A transport
    handing ``dispatch`` an ``extra_kwargs`` overlay fills keywords this
    cannot see, and should not call it for such a spec. The output
    selector, an ``extend_queryset``, the preconditions and the affordance
    conditions are not read.

    ``spec`` may be a declaration with ``as_kernel_spec()``, read as the spec
    it compiles to.

    Raises:
        ImproperlyConfigured: any of the four, or a callable whose
            signature cannot be read, every one found.
    """
    spec = kernel_spec(spec)
    problems: list[str] = []
    _, taken = split_seed_named(spec, spec.parameters(), pool_seeds)
    if taken:
        problems.append(seed_named_refusal(spec, taken, pool_seeds))
    filled_everywhere = EVERY_POOL | pool_seeds.names
    for seat in _seats(spec):
        problems += _unfilled(seat, filled_everywhere)
    if problems:
        raise ImproperlyConfigured(" ".join(problems))


@dataclass(frozen=True)
class _Seat:
    """A callable a call binds from its pool, and what fills that pool.

    ``handed`` is what the pool carries beyond every pool's own and the
    registered seeds; ``validated`` is whether a Validator's values join it.
    """

    label: str
    fn: Callable[..., Any]
    reads: Parameters
    provider: Callable[..., Any] | None
    handed: frozenset[str] = frozenset()
    validated: bool = False


def _seats(spec: ServiceSpec | SelectorSpec) -> list[_Seat]:
    """Each callable a call binds by its pool, the target selector before the service, as a call runs them.

    A target selector's pool is a selector's. A service's adds ``data`` and
    the target under the name ``target_entry`` hands it as, the rule
    ``walk_target`` returns it by.
    """
    if isinstance(spec, SelectorSpec):
        return [_Seat(SELECTOR_SOURCE, spec.selector, spec.reads, spec.kwargs)]
    seats: list[_Seat] = []
    target = spec.target_selector_spec()
    if target is not None:
        label = INSTANCE_SOURCE if spec.instance_selector_spec is not None else COLLECTION_SOURCE
        seats.append(_Seat(label, target.selector, target.reads, target.kwargs))
    seats.append(
        _Seat(
            _SERVICE_SOURCE,
            spec.service,
            spec.reads,
            spec.kwargs,
            handed=frozenset({"data"}) | target_entry(spec, None).keys(),
            validated=spec.validator is not None,
        )
    )
    return seats


def _unfilled(seat: _Seat, filled: frozenset[str]) -> list[str]:
    """The second, third and fourth refusals, for one seat, or the one that precedes them."""
    try:
        signature = inspect.signature(seat.fn)
    except (ValueError, TypeError):
        # A callable with no signature to read - a builtin type such as
        # ``dict``, or one whose ``__signature__`` is no ``Signature`` - is
        # refused by this and answers none of the three below, which all read
        # that signature (``required_keywords`` reads it again, and is never
        # reached). Dispatch reads it too, so every call reaching the seat
        # fails with the same error. Returning, not raising, leaves the other
        # seats' refusals to be collected beside it. One arc for two
        # exceptions, each held by its own test:
        # test_it_is_refused_naming_the_seat_and_the_callable (``ValueError``)
        # and test_a_signature_that_is_not_one_is_refused_alike
        # (``TypeError``).
        return [
            f"{seat.label} is {seat.fn!r}, whose signature cannot be read, so dispatch can "
            "bind no keyword to it and every call reaching it fails. Declare it as a "
            "function that takes the keywords it needs."
        ]
    problems: list[str] = []
    positional = sorted(
        name
        for name, param in signature.parameters.items()
        if param.kind is inspect.Parameter.POSITIONAL_ONLY
        and param.default is inspect.Parameter.empty
    )
    if positional:
        # Whatever could fill the name, since no pool fills a positional:
        # test_it_is_refused_whatever_could_fill_it_by_name. One arc; the
        # kind is held by test_without_the_seed_the_read_is_the_caller_s, a
        # keyword-only parameter with no default, and the default by
        # test_one_with_a_default_is_not.
        problems.append(
            f"{seat.label} takes the positional-only parameter(s) {positional} with no "
            "default, which dispatch never fills: it calls every callable by keyword. Make "
            "each one a keyword, or give it a default."
        )
    keys = provider_keys(seat.provider)
    # A provider that says nothing about its keys may fill any of them
    # (test_a_keyword_something_fills_is_not's ``untyped`` case), and a
    # Validator may return or bind a value it never declares
    # (test_a_service_beside_a_validator_is_left_to_dispatch): one arc, each
    # held by its own test.
    if keys is None or seat.validated:
        return problems
    filled = filled | seat.handed | keys.filled | keys.declinable
    required = [name for name in required_keywords(seat.fn) if name not in filled]
    # The shape check's own reading of a demanded parameter (``check_arguments``).
    demanded = frozenset(
        param.name for param in seat.reads if param.required and param.default is UNSET
    )
    declared = seat.reads.names()
    unfilled = sorted(name for name in required if name not in declared)
    optional = sorted(name for name in required if name in declared - demanded)
    if unfilled:
        problems.append(
            f"{seat.label} requires the keyword(s) {unfilled}, which nothing fills: no read "
            "or Validator field declares it, no registered seed is named so and no provider "
            "is annotated to return it, so every call reaching it would fail. Declare it, or "
            "give it a default."
        )
    if optional:
        problems.append(
            f"{seat.label} requires the keyword(s) {optional}, declared as optional reads "
            "that nothing else fills, so a call leaving one out is refused as missing. "
            "Declare the read required, or give the keyword a default."
        )
    return problems
