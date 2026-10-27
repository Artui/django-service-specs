"""``check_seeds`` - a spec no call on a mount could run, refused before any call."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.dispatch.utils import (
    COLLECTION_SOURCE,
    INSTANCE_SOURCE,
    SELECTOR_SOURCE,
    seed_named_fields,
    seed_named_refusal,
    split_seed_named,
    target_entry,
)
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.pool.call_seeds import CALL_SEEDS
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.pool.provider_keys import provider_keys
from django_service_specs.selectors.utils import required_keywords
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.types.unset import UNSET
from django_service_specs.types.utils import CALL_CONTEXT, SHAPES
from django_service_specs.validation.validator import Validator

_SERVICE_SOURCE: Final = "ServiceSpec.service"

_EVERY_POOL: Final = frozenset({"user", "progress", CALL_CONTEXT, SHAPES}) | CALL_SEEDS
"""What every pool dispatch builds carries, whatever the mount registers.

``base_pool``'s ``user`` and ``progress``, the call's context and the
``shapes`` dispatch adds beside them, and the call's ``request`` and ``view``,
handed to a callable naming either (test_a_keyword_something_fills_is_not's
``every-pool-s-own`` case).
"""


def check_seeds(
    spec: ServiceSpec | SelectorSpec | SpecSource, *, pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS
) -> None:
    """Refuse a spec that no call on a mount registering ``pool_seeds`` could run as declared.

    For a transport registering a kernel spec: what each refusal below names
    is decided by the spec and the mount's registered seeds alone, so it is
    the same for every call, and the transport can refuse the spec where it
    is registered rather than list a tool or a route that fails each time.
    The spec is not refused by itself when it is built because the seeds are
    the mount's, and a keyword one mount fills is unfilled on another.
    Nothing runs: no seed resolves, no provider is called and no query is
    made. Every refusal it finds is named in one ``ImproperlyConfigured``,
    each offender in a sorted list such as ``['tenant']``.

    1. **A parameter a registered seed is named like**, or ``request`` or
       ``view``, that dispatch refuses on every call: a read nobody marked
       ``reflected``, a shape, a ``many`` spec's list
       ([`seed_named_parameters`][django_service_specs.dispatch.seed_named_parameters.seed_named_parameters]'s
       second set), in the words dispatch refuses it in.
    2. **A positional-only parameter with no default**, of the service, the
       selector or the target selector. Dispatch calls each by keyword, so
       nothing fills one, a read of its name included.
    3. **A keyword the callable requires that nothing fills**: by name, with
       no default, and in none of the places dispatch fills a keyword from
       - what every pool carries (``user``, ``progress``, ``call_context``,
       ``shapes``, ``request``, ``view``), a seed ``pool_seeds`` registers,
       a read of the callable's own seat, a key the seat's typed ``kwargs``
       provider names, and for a service ``data``, and ``instance`` or
       ``collection`` where a target selector resolves one. The kernel seeds
       ``data`` for a service only, so a selector requiring it is refused as
       any unfilled keyword is. A service is handed its spec's reads, never
       its target selector's or its shapes, which reach it as ``shapes``.
    4. **A keyword the callable requires that only an optional read fills**:
       a read the shape check does not demand - declared ``required=False``,
       or declaring a ``default``, which is reported and never applied - over
       a keyword with no default, that no seed and no provider fills. A call
       sending it runs, and one leaving it out is refused as missing
       (``call_keywords``), so a caller reading the declaration is told the
       read is optional and refused for omitting it.
    5. **A Validator field the service cannot receive**: one the service
       takes neither by name, nor through ``data``, nor through
       ``**kwargs``, so a value sent for it is validated and dropped. A
       top-level field named like a seed or the call's ``request`` or
       ``view`` reaches the service through ``data`` alone, since the name
       in the pool is the seed's. A ``many`` spec's rows reach it as the list
       under ``many_argument``, or in ``data``. **This one runs**: such a
       spec dispatches today, and is refused here because a transport
       advertising the field would advertise a value nobody reads, which is
       why it is in this reader and never in the spec's own construction.

    **What it cannot see, and so never refuses.** A provider whose return
    says nothing about its keys may fill any keyword in its seat, so that
    seat's keywords are left to dispatch (the third and fourth). A
    Validator may return a value it does not declare, or bind one, so a
    service beside a Validator is not judged by the third and fourth either
    (test_a_service_beside_a_validator_is_left_to_dispatch). A Validator may
    return a field under a name other than its parameter's - a pydantic
    field validated by its alias comes back under its own name - so a
    service taking a keyword nothing declared explains is held to the fifth
    for none of its fields
    (test_a_field_validated_under_its_alias_reaches_its_own_name_and_is_not).
    A transport handing ``dispatch`` an ``extra_kwargs`` overlay fills
    keywords this cannot see, and should not call it for such a spec. The
    output selector, an ``extend_queryset``, the preconditions and the
    affordance conditions are not read.

    ``spec`` may be a declaration with ``as_kernel_spec()``, read as the spec
    it compiles to.

    Raises:
        ImproperlyConfigured: any of the five, every one found.
    """
    spec = kernel_spec(spec)
    problems: list[str] = []
    _, taken = split_seed_named(spec, spec.parameters(), pool_seeds)
    if taken:
        problems.append(seed_named_refusal(spec, taken, pool_seeds))
    filled_everywhere = _EVERY_POOL | pool_seeds.names
    for seat in _seats(spec):
        problems += _unfilled(seat, filled_everywhere)
    if isinstance(spec, ServiceSpec) and spec.validator is not None:
        problems += _dropped_fields(spec, spec.validator, pool_seeds, filled_everywhere)
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
    """The second, third and fourth refusals, for one seat."""
    problems: list[str] = []
    positional = sorted(
        name
        for name, param in inspect.signature(seat.fn).parameters.items()
        if param.kind is inspect.Parameter.POSITIONAL_ONLY
        and param.default is inspect.Parameter.empty
    )
    if positional:
        # Whatever could fill the name, since no pool fills a positional:
        # test_it_is_refused_whatever_could_fill_it_by_name. One arc; the
        # kind is held by every case of test_a_keyword_something_fills_is_not
        # and the default by test_one_with_a_default_is_not.
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
            "is annotated to return it, so every call would fail. Declare it, or give it a "
            "default."
        )
    if optional:
        problems.append(
            f"{seat.label} requires the keyword(s) {optional}, declared as optional reads "
            "that nothing else fills, so a call leaving one out is refused as missing. "
            "Declare the read required, or give the keyword a default."
        )
    return problems


def _dropped_fields(
    spec: ServiceSpec, validator: Validator, pool_seeds: PoolSeeds, filled: frozenset[str]
) -> list[str]:
    """The fifth refusal: the Validator's fields the service is never handed."""
    params = inspect.signature(spec.service).parameters
    named = frozenset(
        name
        for name, param in params.items()
        if param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    )
    # ``data`` carries every field, and a ``many`` spec's every row.
    if "data" in named:
        return []
    fields = frozenset({spec.many_argument}) if spec.many else validator.parameters().names()
    keys = provider_keys(spec.kwargs)
    # A keyword nothing declared explains may be a field returned under a name
    # of its own, so then no field is judged; an untyped provider explains
    # every keyword. One arc, each held by its own test:
    # test_a_field_validated_under_its_alias_reaches_its_own_name_and_is_not
    # and the ``untyped`` case of test_a_field_the_service_receives_is_not.
    if keys is None or named - (
        filled
        | {"data"}
        | target_entry(spec, None).keys()
        | spec.reads.names()
        | fields
        | keys.filled
        | keys.declinable
    ):
        return []
    seed_named = seed_named_fields(spec, pool_seeds.names | CALL_SEEDS)
    takes_all = any(param.kind is inspect.Parameter.VAR_KEYWORD for param in params.values())
    # Each part held by its own case: test_a_field_named_like_a_seed_reaches_the_service_through_data_alone
    # (``seed_named``), test_a_field_the_service_receives_is_not's ``through-kwargs``
    # (``takes_all``) and ``by-name`` (``named``).
    dropped = sorted(
        name for name in fields if name in seed_named or not (takes_all or name in named)
    )
    if not dropped:
        return []
    note = (
        " A field named like a registered seed or the call's own reaches the service through "
        "data alone, since the name in its pool is the seed's."
        if set(dropped) & seed_named
        else ""
    )
    return [
        f"ServiceSpec.validator declares the field(s) {dropped}, which {_SERVICE_SOURCE} "
        "takes neither by name nor through data or **kwargs, so a value sent for one is "
        f"validated and dropped. Take it, or remove the field.{note}"
    ]
