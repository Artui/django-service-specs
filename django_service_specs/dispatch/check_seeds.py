from __future__ import annotations

import functools
import inspect
import types
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Final, TypeVar, Union, get_args, get_origin

import typing_extensions
from django.core.exceptions import ImproperlyConfigured
from typing_extensions import get_type_hints

from django_service_specs.affordances.utils import ambient_pool
from django_service_specs.dispatch.utils import (
    COLLECTION_SOURCE,
    EVERY_POOL,
    INSTANCE_SOURCE,
    OUTPUT_SOURCE,
    SELECTOR_SOURCE,
    reach,
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
from django_service_specs.types.affordance import Affordance
from django_service_specs.types.provider_keys import ProviderKeys
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.types.unset import UNSET
from django_service_specs.types.utils import callable_name, is_row_condition

_SERVICE_SOURCE: Final = "ServiceSpec.service"
_SEQUENCES: Final = (list, tuple, Sequence)
# ``typing_extensions.Any`` is its own object before Python 3.11.
_ANY_ELEMENT: Final = (None, Any, typing_extensions.Any, object)
_BY_KEYWORD: Final = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)

# The keys dispatch writes into a pool as literals, mirrored here. Each is
# held by a test dispatching a callable that requires it and seeing it run
# (TestWhatEachSeatTheFifthSkipsIsHanded), so a key dispatch renames fails there.
# The row a RETRIEVE selector spec's preconditions are handed
# (``conclude_selector``), and the service's return in the output selector's
# pool (``finish_service``).
_INSTANCE: Final = "instance"
# The rows a LIST selector spec's preconditions are handed (``conclude_selector``).
_COLLECTION: Final = "collection"
# The service's return in the output selector's pool (``finish_service``).
_RESULT: Final = "result"
# What ``extend_queryset`` shapes (``apply_shaping``).
_QUERYSET: Final = "queryset"

# The spec each selector seat belongs to, as its construction refusals name it.
_SPEC_LABELS: Final[Mapping[str, str]] = {
    SELECTOR_SOURCE: "SelectorSpec",
    INSTANCE_SOURCE: "ServiceSpec.instance_selector_spec",
    COLLECTION_SOURCE: "ServiceSpec.collection_selector_spec",
    OUTPUT_SOURCE: "ServiceSpec.output_selector_spec",
}

# Why nothing fills a keyword, per seat: the rest of the third refusal.
_UNDECLARED: Final = (
    "no read or Validator field declares it, no registered seed is named so and no provider "
    "is annotated to return it, so every call reaching it would fail. Declare it, or give it "
    "a default."
)
_UNSEEDED: Final = (
    "a condition is handed only the call's seeds - user, progress, call_context, request, "
    "view and those this mount registers - so every call reaching it would fail. Register "
    "the seed on the mount, or give it a default."
)
_UNRETURNED: Final = (
    "an output selector is handed the service's return as instance and result and the "
    "call's seeds, never an argument, so every call reaching it would fail. Read it from "
    "result, register the seed on the mount, or give it a default."
)
_UNPROVIDED: Final = (
    "a provider is handed what every pool carries - user, progress, call_context, shapes, "
    "request, view - the seeds this mount registers and its seat's reads, and for a service "
    "the target as instance or collection; never data, a Validator's value, nor a read a "
    "kwargs provider is typed to fill, so every call reaching it would fail. Register the "
    "seed on the mount, declare the read, or give it a default."
)
_UNREPORTED: Final = (
    "a progress_reporter is handed only the call's seeds - user, progress, call_context, "
    "shapes, request, view and those this mount registers - so every call reaching it would "
    "fail. Register the seed on the mount, or give it a default."
)
# What a call leaving out an optional read a seat requires meets: the fourth
# refusal's account of it. A provider is bound by ``pool_kwargs``, which never
# refuses, so the provider raises.
_REFUSED_AS_MISSING: Final = "is refused as missing"
_PROVIDER_RAISES: Final = "fails with the provider's own TypeError"


def check_seeds(
    spec: ServiceSpec | SelectorSpec | SpecSource, *, pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS
) -> None:
    """Refuse a declaration that cannot hold as written on a mount registering ``pool_seeds``.

    Five of them, below: a parameter a seed or the call's own value would
    meet, a positional-only parameter dispatch cannot pass, a keyword nothing
    fills, an optional read over a keyword that requires it, and an array
    read with no ``items`` over a keyword annotated with its element. The
    first fails every call, the second and third every call that reaches the
    callable, the fourth every call leaving the read out, which the
    declaration says a caller may, and the fifth hands the callable any
    element a caller sends. Each is decided by the spec and the
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
       selector or the target selector, and of each callable the third reads
       below: a precondition, a callable condition, the output selector, an
       ``extend_queryset``, a ``kwargs`` or ``input_data`` provider and a
       ``progress_reporter``. Dispatch calls each by keyword, so nothing
       fills one, a read of its name included.
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
       ``shapes``. It reads these callables, each against what dispatch
       hands that one:

       - the service, the selector and the target selector, as above;
       - a service spec's ``preconditions``, handed the service's pool, and
         a selector spec's, handed the selector's with the rows as
         ``collection`` (a LIST) or the row as ``instance`` (a RETRIEVE);
       - each callable ``Affordance`` condition, the spec's own and those
         a selector's ``affordances`` map to, handed only the call's seeds:
         ``user``, ``progress``, ``call_context``, ``request``, ``view``
         and a seed ``pool_seeds`` registers, never an argument
         (``ambient_pool``); a condition on the row binds nothing;
       - the output selector, handed the service's return as ``instance``
         and ``result`` and what every pool carries, never an argument nor
         its own reads;
       - each selector's ``extend_queryset``, handed its selector's pool
         with the ``queryset``;
       - each ``kwargs`` provider - the spec's own and its target
         selector's - and a service spec's ``input_data``, handed what
         every pool carries, a seed ``pool_seeds`` registers and its seat's
         reads less those the seat's typed ``kwargs`` provider fills, whose
         caller's value dispatch drops; for a service, ``instance`` or
         ``collection`` where a target selector resolves one. Never
         ``data``, a Validator's value or a provider's answer: ``input_data``
         runs before the Validator, and ``kwargs`` is called from the same
         pool. A provider's own keys fill nothing it is handed, so its seat
         is read whether it is typed or not, and beside a Validator too;
       - a spec's ``progress_reporter``, where its run takes ``progress`` by
         name or through ``**kwargs``, which is where dispatch may call it:
         before an ``async def`` run, or on a sync run's first report. It is
         refused either way, though a sync run that never reports never
         calls it. It is handed only what every pool carries and a seed
         ``pool_seeds`` registers. A run taking no ``progress`` never calls
         it, so it is not read there.

       Each is named as the spec names it, such as
       ``ServiceSpec.affordances[0] ('frozen').when``,
       ``SelectorSpec.preconditions[0] (owns_it)`` or
       ``ServiceSpec.instance_selector_spec.kwargs``, in the order a call
       reaches it.
    4. **A keyword the callable requires that only an optional read fills**:
       a read the shape check does not demand - declared ``required=False``,
       or declaring a ``default``, which is reported and never applied - over
       a keyword with no default, that no seed and no provider fills. A call
       sending it runs, and one leaving it out is refused as missing
       (``call_keywords``), or on a provider fails with its own
       ``TypeError``, so a caller reading the declaration is told the read
       is optional and refused for omitting it. It reads every callable the
       third does that sees reads: a precondition, an ``extend_queryset``
       and a ``kwargs`` or ``input_data`` provider as well as the service,
       the selector and the target selector. A condition, the output
       selector and a ``progress_reporter`` are handed none of their spec's
       reads, so it finds nothing on them.
    5. **An array read with no ``items`` over a keyword annotated with its
       element**: a read of ``type="array"`` declaring no ``items``, over
       the keyword it fills on its own seat, annotated ``list[X]``,
       ``tuple[X, ...]`` or ``Sequence[X]``, or one of those ``| None``,
       where ``X`` is neither ``Any``, ``object`` nor a type variable. Such
       a read takes any
       element, so a callable annotated ``pks: list[int]`` is handed a
       query string's strings, and the message says to declare ``items``.
       It derives none from the annotation: a signature is not a
       declaration. As with the third and fourth, it never guesses: a
       keyword a provider fills or may fill is not one - a typed
       provider's key, declinable or not, and any keyword of a seat whose
       provider is untyped - and nor is a keyword a seed fills, as a
       ``reflected`` read's.

    **A callable whose signature cannot be read** is refused too, ahead of
    these for its seat: any callable the third reads, such as a builtin type
    like ``dict``, which dispatch cannot bind a keyword to and so fails on
    for every call reaching it. The second to fifth need that signature, so
    such a seat is answered by this refusal alone, and the other seats are
    still checked.

    A Validator field the service never receives is not among them, because
    such a spec runs and may mean to:
    [`unreceived_fields`][django_service_specs.dispatch.unreceived_fields.unreceived_fields]
    answers it, and the transport decides.

    **What it cannot see, and so never refuses.** A provider whose return says
    nothing about its keys may fill any keyword of the callable it provides
    for, so that callable's keywords are left to dispatch (the third and
    fourth); the provider's own are read as any seat's. An annotation that
    does not resolve, as a forward reference to a name not importable where the
    callable was defined, is not read, and leaves alone only its own keyword
    (the fifth); so is a bare ``list``, an element of ``Any`` or ``object``, a
    fixed-length ``tuple``, a union of two sequences and an unannotated
    keyword. A Validator may return a value it does not declare, or bind one,
    so a service beside a Validator is not judged by the third and fourth
    either (test_a_service_beside_a_validator_is_left_to_dispatch). A transport
    handing ``dispatch`` an ``extra_kwargs`` overlay fills keywords this cannot
    see, and should not call it for such a spec. Only the fifth refusal is not
    run on a precondition, a condition, the output selector, an
    ``extend_queryset``, a provider or a ``progress_reporter``. A precondition beside a Validator,
    or one or an
    ``extend_queryset`` beside an untyped provider, is left to dispatch by the
    third and fourth as the callable beside it is, never by the second. A
    callable taking ``**kwargs`` requires nothing, so one forwarding into a
    stricter callable is not judged by what that callable requires. Nor is the
    pool a transport builds itself to answer a condition at describe time
    (``unmet_operation_affordance``): this reads the pool dispatch builds. Nor
    does it read a ``filter_set``, a form's ``form_kwargs`` or a seed's
    resolver: dispatch binds each by keyword, and this is not asked of any.

    **Describe-time**: run where a transport registers the spec, it reads
    the spec as it declares itself to no call, handing a Validator that
    declares ``call_context`` ``None``
    (test_describe_time_readers_hand_none).
    It takes no ``call_context``, unlike the input schemas, because none of
    its five refusals reads a Validator's field: what it refuses is a read, a
    shape, a ``many`` spec's list and a callable's keywords, a top-level
    Validator field is in neither of ``seed_named_parameters``' sets, and a
    service beside a Validator is left to dispatch
    (test_a_validator_field_is_the_caller_s_and_fills_the_service_s_keyword).
    Assembling ``spec.parameters()`` still refuses a seat dispatch seeds
    itself, a name two sources declare and a field a typed ``kwargs`` fills.
    So a field declared only to one transport with such a shape is not refused
    here, and raises at the first ask under that stamp, a schema's as well as
    dispatch's
    (test_a_declaration_only_a_transport_makes_is_refused_when_that_transport_asks).

    ``spec`` may be a declaration with ``as_kernel_spec()``, read as the spec
    it compiles to.

    Raises:
        ImproperlyConfigured: any of the five, or a callable whose
            signature cannot be read, every one found.
    """
    spec = kernel_spec(spec)
    problems: list[str] = []
    _, taken = split_seed_named(spec, spec.parameters(), pool_seeds)
    if taken:
        problems.append(seed_named_refusal(spec, taken, pool_seeds))
    for seat in _seats(spec, pool_seeds):
        problems += _refusals(seat)
    if problems:
        raise ImproperlyConfigured(" ".join(problems))


@dataclass(frozen=True)
class _Seat:
    """A callable a call binds from its pool, and what fills that pool."""

    label: str
    fn: Callable[..., Any]
    reads: Parameters
    provider: Callable[..., Any] | None
    fills: frozenset[str]
    validated: bool = False
    checks_items: bool = True
    unfilled: str = _UNDECLARED
    omitted: str = _REFUSED_AS_MISSING


def _seats(spec: ServiceSpec | SelectorSpec, pool_seeds: PoolSeeds) -> list[_Seat]:
    """Each callable a call binds by its pool, in the order a call reaches them."""
    everywhere = EVERY_POOL | pool_seeds.names
    conditions = _condition_fills(everywhere, pool_seeds)
    if isinstance(spec, SelectorSpec):
        own = _Seat(SELECTOR_SOURCE, spec.selector, spec.reads, spec.kwargs, everywhere)
        row = _COLLECTION if spec.kind is SelectorKind.LIST else _INSTANCE
        reporter = _reporting("SelectorSpec", spec.progress_reporter, spec.selector, everywhere)
        return [
            *_selector_provider(spec, own.label, everywhere),
            *_selector_seats(spec, own, conditions, beside=reporter),
            *_preconditions(spec, "SelectorSpec", replace(own, fills=own.fills | {row})),
        ]
    seats: list[_Seat] = []
    target = spec.target_selector_spec()
    if target is not None:
        source = INSTANCE_SOURCE if spec.instance_selector_spec is not None else COLLECTION_SOURCE
        seat = _Seat(source, target.selector, target.reads, target.kwargs, everywhere)
        seats += _selector_provider(target, source, everywhere)
        seats += _selector_seats(target, seat, conditions)
    provided = everywhere | target_entry(spec, None).keys()
    reads = _handed(spec.reads, spec.kwargs)
    seats += _provided("ServiceSpec.input_data", spec.input_data, reads, provided)
    seats += _provided("ServiceSpec.kwargs", spec.kwargs, reads, provided)
    service = _Seat(
        _SERVICE_SOURCE,
        spec.service,
        spec.reads,
        spec.kwargs,
        everywhere | {"data"} | target_entry(spec, None).keys(),
        validated=spec.validator is not None,
    )
    seats += _conditions("ServiceSpec.affordances", spec.affordances, conditions)
    seats += _preconditions(spec, "ServiceSpec", service)
    seats.append(service)
    seats += _reporting("ServiceSpec", spec.progress_reporter, spec.service, everywhere)
    output = spec.output_selector_spec
    if output is not None:
        seat = _Seat(
            OUTPUT_SOURCE,
            output.selector,
            Parameters.of(),
            None,
            everywhere | {_INSTANCE, _RESULT},
            checks_items=False,
            unfilled=_UNRETURNED,
        )
        seats += _selector_seats(output, seat, conditions)
    return seats


def _condition_fills(everywhere: frozenset[str], pool_seeds: PoolSeeds) -> frozenset[str]:
    """What a callable affordance condition is handed: ``ambient_pool`` plus the call's two."""
    ambient = ambient_pool(dict.fromkeys(everywhere), reserved=pool_seeds.reserved)
    return frozenset(ambient) | CALL_SEEDS


def _handed(reads: Parameters, provider: Callable[..., Any] | None) -> Parameters:
    """``reads`` less those ``provider`` is annotated to fill: what its seat is handed."""
    filled, _ = reach(provider, reads)
    return Parameters.of(*(param for param in reads if param.name not in filled))


def _provided(
    label: str, provider: Callable[..., Any] | None, reads: Parameters, fills: frozenset[str]
) -> list[_Seat]:
    """A seat for ``provider``, handed ``fills`` and ``reads`` alone; none where it is unset."""
    if provider is None:
        return []
    return [
        _Seat(
            label,
            provider,
            reads,
            None,
            fills,
            checks_items=False,
            unfilled=_UNPROVIDED,
            omitted=_PROVIDER_RAISES,
        )
    ]


def _selector_provider(spec: SelectorSpec, source: str, fills: frozenset[str]) -> list[_Seat]:
    """A selector's ``kwargs`` seat: called from ``selector_pool`` before the answer joins it."""
    label = f"{_SPEC_LABELS[source]}.kwargs"
    return _provided(label, spec.kwargs, _handed(spec.reads, spec.kwargs), fills)


def _reporting(
    label: str, reporter: Callable[..., Any] | None, run: Callable[..., Any], fills: frozenset[str]
) -> list[_Seat]:
    """A seat for a spec's ``progress_reporter``, where dispatch may call it; none elsewhere."""
    if reporter is None:
        return []
    try:
        parameters = inspect.signature(run).parameters.values()
    except (ValueError, TypeError):
        return []
    takes = any(
        param.kind is inspect.Parameter.VAR_KEYWORD
        or (param.name == "progress" and param.kind in _BY_KEYWORD)
        for param in parameters
    )
    if not takes:
        return []
    return [
        _Seat(
            f"{label}.progress_reporter",
            reporter,
            Parameters.of(),
            None,
            fills,
            checks_items=False,
            unfilled=_UNREPORTED,
        )
    ]


def _selector_seats(
    spec: SelectorSpec,
    seat: _Seat,
    conditions: frozenset[str],
    *,
    beside: Sequence[_Seat] = (),
) -> list[_Seat]:
    """A selector's seat and those beside it, then its affordance and queryset conditions."""
    label = _SPEC_LABELS[seat.label]
    seats = [seat, *beside]
    for name, declarer in (spec.affordances or {}).items():
        seats += _conditions(f"{label}.affordances[{name!r}]", declarer.affordances, conditions)
    if spec.extend_queryset is not None:
        seats.append(
            replace(
                seat,
                label=f"{label}.extend_queryset",
                fn=spec.extend_queryset,
                fills=seat.fills | {_QUERYSET},
                checks_items=False,
                unfilled=f"it is handed {_QUERYSET} beside what its selector is handed, and "
                + seat.unfilled,
            )
        )
    return seats


def _conditions(
    label: str, affordances: Sequence[Affordance] | None, fills: frozenset[str]
) -> list[_Seat]:
    """A seat per callable condition in ``affordances``, named by index and code as spec does."""
    return [
        _Seat(
            f"{label}[{index}] ({affordance.code!r}).when",
            affordance.when,
            Parameters.of(),
            None,
            fills,
            checks_items=False,
            unfilled=_UNSEEDED,
        )
        for index, affordance in enumerate(affordances or ())
        if not is_row_condition(affordance.when)
    ]


def _preconditions(spec: ServiceSpec | SelectorSpec, label: str, seat: _Seat) -> list[_Seat]:
    """``seat`` with each precondition in its callable's place, named as dispatch names one."""
    return [
        replace(
            seat,
            label=f"{label}.preconditions[{index}] ({callable_name(precondition)})",
            fn=precondition,
            checks_items=False,
        )
        for index, precondition in enumerate(spec.preconditions or ())
    ]


def _refusals(seat: _Seat) -> list[str]:
    """The second to fifth refusals for one seat, or the one that precedes them."""
    try:
        signature = inspect.signature(seat.fn)
    except (ValueError, TypeError):
        return [
            f"{seat.label} is {seat.fn!r}, whose signature cannot be read, so dispatch can "
            "bind no keyword to it and every call reaching it fails. Declare it as a "
            "function that takes the keywords it needs."
        ]
    return _every_check(seat, signature, provider_keys(seat.provider))


def _every_check(seat: _Seat, signature: inspect.Signature, keys: ProviderKeys | None) -> list[str]:
    """The second to fifth refusals for one seat; the fifth only where ``checks_items``."""
    problems: list[str] = []
    positional = sorted(
        name
        for name, param in signature.parameters.items()
        if param.kind is inspect.Parameter.POSITIONAL_ONLY
        and param.default is inspect.Parameter.empty
    )
    if positional:
        problems.append(
            f"{seat.label} takes the positional-only parameter(s) {positional} with no "
            "default, which dispatch never fills: it calls every callable by keyword. Make "
            "each one a keyword, or give it a default."
        )
    untyped = _untyped_elements(seat, signature, keys, seat.fills) if seat.checks_items else []
    if untyped:
        problems.append(
            f"{seat.label} reads the array(s) {untyped} with no items into keywords annotated "
            "with their element type, so each is handed any element a caller sends, such as a "
            "query string's strings. Declare each one's items."
        )
    if keys is None or seat.validated:
        return problems
    required = _required(seat, keys)
    demanded = frozenset(
        param.name for param in seat.reads if param.required and param.default is UNSET
    )
    unfilled = _unfilled(seat, required)
    optional = sorted(name for name in required if name in seat.reads.names() - demanded)
    if unfilled:
        problems.append(_nothing_fills(seat, unfilled))
    if optional:
        problems.append(
            f"{seat.label} requires the keyword(s) {optional}, declared as optional reads "
            f"that nothing else fills, so a call leaving one out {seat.omitted}. "
            "Declare the read required, or give the keyword a default."
        )
    return problems


def _required(seat: _Seat, keys: ProviderKeys) -> list[str]:
    """Keywords ``seat``'s callable requires that neither its pool's names nor its provider fill."""
    filled = seat.fills | keys.filled | keys.declinable
    return [name for name in required_keywords(seat.fn) if name not in filled]


def _unfilled(seat: _Seat, required: list[str]) -> list[str]:
    """Those of ``required`` no read of the seat declares, sorted: the third refusal's offenders."""
    declared = seat.reads.names()
    return sorted(name for name in required if name not in declared)


def _nothing_fills(seat: _Seat, unfilled: list[str]) -> str:
    return f"{seat.label} requires the keyword(s) {unfilled}, which nothing fills: {seat.unfilled}"


def _untyped_elements(
    seat: _Seat, signature: inspect.Signature, keys: ProviderKeys | None, seeded: frozenset[str]
) -> list[str]:
    """The fifth refusal's offenders: an array with no ``items``, over a typed keyword."""
    if keys is None:
        return []
    filled_by_provider = keys.filled | keys.declinable
    taken = {
        name: param.annotation
        for name, param in signature.parameters.items()
        if param.kind in _BY_KEYWORD
    }
    candidates = [
        param.name
        for param in seat.reads
        if param.type == "array"
        and param.items is None
        and param.name in taken
        and param.name not in seeded | filled_by_provider
    ]
    namespace = _namespace(seat.fn)
    elements = {name: _element(_hint(taken[name], namespace)) for name in candidates}
    return sorted(
        name
        for name, element in elements.items()
        if element not in _ANY_ELEMENT and not isinstance(element, TypeVar)
    )


def _namespace(fn: Callable[..., Any]) -> dict[str, Any]:
    """The globals of the function ``inspect.signature`` reads ``fn``'s parameters off."""
    while isinstance(fn, functools.partial):
        fn = fn.func
    if isinstance(fn, type):
        fn = fn.__init__
    elif not inspect.isroutine(fn):
        fn = type(fn).__call__
    return getattr(inspect.unwrap(fn), "__globals__", {})


def _hint(annotation: Any, namespace: dict[str, Any]) -> Any:
    """``annotation`` evaluated as ``get_type_hints`` does, or ``None`` if unresolvable."""
    try:
        holder = types.SimpleNamespace(__annotations__={"value": annotation})
        return get_type_hints(holder, globalns=namespace)["value"]
    except Exception:
        return None


def _element(hint: Any) -> Any:
    """The element of a parametrised sequence ``hint``, or ``None`` otherwise."""
    if get_origin(hint) in (Union, types.UnionType):
        arms = [arm for arm in get_args(hint) if arm is not type(None)]
        hint = arms[0] if len(arms) == 1 else None
    origin, args = get_origin(hint), get_args(hint)
    if origin not in _SEQUENCES or not args:
        return None
    if origin is tuple:
        return args[0] if len(args) == 2 and args[1] is Ellipsis else None
    return args[0]
