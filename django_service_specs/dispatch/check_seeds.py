"""``check_seeds`` - a declaration that cannot hold on a mount as written, refused before any call."""

from __future__ import annotations

import inspect
import types
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final, Union, get_args, get_origin

import typing_extensions
from django.core.exceptions import ImproperlyConfigured
from typing_extensions import Format, get_annotations, get_type_hints

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
from django_service_specs.types.provider_keys import ProviderKeys
from django_service_specs.types.unset import UNSET

_SERVICE_SOURCE: Final = "ServiceSpec.service"
_SEQUENCES: Final = (list, tuple, Sequence)
# ``typing_extensions.Any`` is its own object before Python 3.11.
_ANY_ELEMENT: Final = (None, Any, typing_extensions.Any, object)
_BY_KEYWORD: Final = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)


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
    5. **An array read with no ``items`` over a keyword annotated with its
       element**: a read of ``type="array"`` declaring no ``items``, over
       the keyword it fills on its own seat, annotated ``list[X]``,
       ``tuple[X, ...]`` or ``Sequence[X]``, or one of those ``| None``,
       where ``X`` is neither ``Any`` nor ``object``. Such a read takes any
       element, so a callable annotated ``pks: list[int]`` is handed a
       query string's strings, and the message says to declare ``items``.
       It derives none from the annotation: a signature is not a
       declaration. A keyword a typed provider is annotated to fill is not
       one, since the caller's value never reaches it; one the provider
       may decline, or an untyped provider's, is, since the read's value
       reaches it whenever the provider leaves it out. A keyword a seed
       fills, as a ``reflected`` read's, is not one either.

    **A callable whose signature cannot be read** is refused too, ahead of
    these for its seat: a service, selector or target selector such as a
    builtin type like ``dict``, which dispatch cannot bind a keyword to and so
    fails on for every call reaching it. The second to fifth need that
    signature, so such a seat is answered by this refusal alone, and the
    other seats are still checked.

    A Validator field the service never receives is not among them, because
    such a spec runs and may mean to: [`unreceived_fields`][django_service_specs.dispatch.unreceived_fields.unreceived_fields]
    answers it, and the transport decides.

    **What it cannot see, and so never refuses.** A provider whose return
    says nothing about its keys may fill any keyword in its seat, so that
    seat's keywords are left to dispatch (the third and fourth). An
    annotation that does not resolve, as a forward reference to a name not
    importable where the callable was defined, is not read, and leaves
    alone only its own keyword (the fifth); so is a bare ``list``, an element
    of ``Any`` or ``object``, a fixed-length ``tuple``, a union of two
    sequences and an unannotated keyword. A
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
        ImproperlyConfigured: any of the five, or a callable whose
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
    """The second to fifth refusals, for one seat, or the one that precedes them."""
    try:
        signature = inspect.signature(seat.fn)
    except (ValueError, TypeError):
        # A callable with no signature to read - a builtin type such as
        # ``dict``, or one whose ``__signature__`` is no ``Signature`` - is
        # refused by this and answers none of the four below, which all read
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
    untyped = _untyped_elements(seat, signature, keys, filled)
    if untyped:
        problems.append(
            f"{seat.label} reads the array(s) {untyped} with no items into keywords annotated "
            "with their element type, so each is handed any element a caller sends, such as a "
            "query string's strings. Declare each one's items."
        )
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


def _untyped_elements(
    seat: _Seat, signature: inspect.Signature, keys: ProviderKeys | None, seeded: frozenset[str]
) -> list[str]:
    """The fifth refusal's offenders on one seat: its array reads with no ``items`` over a keyword annotated with its element.

    Each read is one only when every condition holds, and each is held by a
    test that fails without it:

    - an array read (test_a_read_of_another_type_is_not);
    - declaring no ``items`` (test_a_declared_items_is_not);
    - over a keyword no seed fills (test_a_reflected_read_a_seed_fills_is_not)
      and no typed provider is annotated to fill
      (test_a_keyword_a_typed_provider_fills_is_not), where an untyped
      provider and a key it may decline still leave the read's value to reach
      it (test_a_keyword_a_provider_may_leave_to_the_read_is_refused);
    - that the seat's callable takes by keyword
      (test_a_positional_only_parameter_the_read_never_fills_is_not), and
      only on the read's own seat
      (test_only_the_seat_the_read_fills_is_read);
    - annotated with a parametrised sequence (``_element``) whose element is
      neither ``Any``, as ``typing`` or ``typing_extensions`` spells it, nor
      ``object`` (the ``list-of-any``, ``list-of-typing-extensions-any`` and
      ``list-of-object`` cases of test_what_it_cannot_misread_is_not; the two
      spellings of ``Any`` are one object from Python 3.11, so each of the
      first two holds its own on 3.10 alone).
    """
    filled_by_provider = keys.filled if keys is not None else frozenset()
    taken = {name for name, param in signature.parameters.items() if param.kind in _BY_KEYWORD}
    candidates = [
        param.name
        for param in seat.reads
        if param.type == "array"
        and param.items is None
        and param.name in taken
        and param.name not in seeded | filled_by_provider
    ]
    annotations = _annotations(seat.fn)
    namespace = getattr(inspect.unwrap(seat.fn), "__globals__", {})
    return sorted(
        name
        for name in candidates
        if _element(_hint(annotations.get(name), namespace)) not in _ANY_ELEMENT
    )


def _annotations(fn: Callable[..., Any]) -> dict[str, Any]:
    """``fn``'s annotations, unevaluated where they do not resolve, or none if it has none to read."""
    try:
        return dict(get_annotations(fn, format=Format.FORWARDREF))
    except Exception:
        # A callable whose signature reads and whose annotations do not, as
        # an instance whose ``__annotations__`` is no dict: nothing is read as
        # annotated (test_a_callable_whose_annotations_cannot_be_read_is_not).
        return {}


def _hint(annotation: Any, namespace: dict[str, Any]) -> Any:
    """``annotation`` evaluated as ``get_type_hints`` evaluates one, or ``None`` if it does not resolve.

    Resolved on its own rather than with the rest of the callable's, which
    ``get_type_hints`` resolves all at once, so a hint that does not resolve
    on another keyword leaves this one readable
    (test_a_hint_that_does_not_resolve_leaves_only_its_own_keyword_alone).
    An unannotated keyword's ``None`` reads as ``NoneType``, which is no
    sequence (test_an_unannotated_keyword_is_not).
    """
    try:
        holder = types.SimpleNamespace(__annotations__={"value": annotation})
        return get_type_hints(holder, globalns=namespace)["value"]
    except Exception:
        # A forward reference to a name not importable here, or a string
        # that is no expression: the check never guesses at it.
        return None


def _element(hint: Any) -> Any:
    """The element of ``hint`` if it is a parametrised sequence, or one ``| None``; ``None`` otherwise.

    Each condition is held by a case of test_it_is_refused or
    test_what_it_cannot_misread_is_not. ``typing.Union`` and
    ``types.UnionType`` are one object from Python 3.14, so the two are one
    membership test rather than two branches, held on Python 3.10 by
    ``Optional`` and ``list-or-none``. A union of two sequences answers
    ``None`` (``two-sequences``), as does a sequence with no parameters
    (``bare-typing-Sequence``) and a tuple of fixed length (``fixed-tuple``
    for the ``Ellipsis``, ``one-tuple`` for the length).
    """
    if get_origin(hint) in (Union, types.UnionType):
        arms = [arm for arm in get_args(hint) if arm is not type(None)]
        hint = arms[0] if len(arms) == 1 else None
    origin, args = get_origin(hint), get_args(hint)
    if origin not in _SEQUENCES or not args:
        return None
    if origin is tuple:
        # Only ``tuple[X, ...]`` is a sequence of one element type.
        return args[0] if len(args) == 2 and args[1] is Ellipsis else None
    return args[0]
