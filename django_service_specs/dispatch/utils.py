"""The phases of a dispatch, written once and shared by every entry point.

Every phase is a plain sync function. ``dispatch`` runs them back to back in
the calling thread; ``adispatch`` runs the same functions inside one
thread-sensitive executor hop, and splits them only around a run it has to
await on the event loop. There is no async copy of any phase, so the two entry
points cannot drift: a fix to a phase is a fix to both.

``bind_arguments`` shares the Validator half, because it is the same step a
transport takes when it binds input for itself.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Literal, cast

from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist
from django.db.models import BooleanField, Value
from django.db.models.manager import BaseManager

from django_service_specs.affordances.enforce_affordances import enforce_affordances
from django_service_specs.affordances.utils import (
    affordance_expression,
    rows_with_affordances,
    split_affordances,
)
from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.authorization.utils import is_deactivated
from django_service_specs.dispatch.authorize import authorize
from django_service_specs.dispatch.authorize_scope import authorize_scope
from django_service_specs.dispatch.authorize_target import authorize_target
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.grant import Grant
from django_service_specs.output.presentation_context import PresentationContext
from django_service_specs.parameters.check_arguments import check_arguments
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.parameters.utils import length_problem
from django_service_specs.pool.base_pool import base_pool
from django_service_specs.pool.null_progress import null_progress
from django_service_specs.pool.pool_seeds import PoolSeeds
from django_service_specs.pool.provider_keys import provider_keys
from django_service_specs.pool.utils import deferred_progress, resolve_progress, resolve_provider
from django_service_specs.selectors.is_queryset import is_queryset
from django_service_specs.selectors.materialize_retrieve import materialize_retrieve
from django_service_specs.selectors.run_selector import run_selector
from django_service_specs.selectors.utils import apply_shaping, call_keywords
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.is_async import is_async
from django_service_specs.types.progress_reporter import ProgressReporter
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.types.unknown_arguments import UnknownArguments
from django_service_specs.types.unset import UNSET
from django_service_specs.validation.validated import Validated
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator

NOT_FOUND = DispatchResult(kind="not_found")
"""A required row that does not exist. Frozen, so one instance serves every call."""


@dataclass(frozen=True)
class Overlay:
    """A call's own keywords beneath the spec's ``kwargs`` provider: ``extra_kwargs``.

    What a transport resolves per call and the spec cannot carry - a view's
    hook returning service keywords, say - handed to ``dispatch`` rather than
    folded into a spec rebuilt for the call, which would lose its provider's
    annotations and its identity. Copied on entry, so the caller's mapping is
    never read again.

    There is no overlay for ``input_data``: every key one could carry to the
    Validator names a parameter the caller sends, so it would stand in for a
    value the permission checks saw. A transport merges such values into the
    arguments it hands dispatch instead, where the checks and the Validator
    read one value (test_there_is_no_input_data_overlay).
    """

    kwargs: Mapping[str, Any] = field(default_factory=dict)


NO_OVERLAY = Overlay()


def refuse_overlaid_parameters(
    spec: ServiceSpec | SelectorSpec, declared: Parameters, overlay: Overlay
) -> None:
    """Refuse an ``extra_kwargs`` key that would stand in for a caller's argument.

    A key naming a parameter the spec declares is refused, as a seed's name
    is: the caller's value for a parameter - a
    read, a Validator field, the target selector's read - is what the
    permission checks are handed and the target selector looks the row up
    by, so an overlay standing in for it would run the call on a value
    neither saw (test_an_extra_kwargs_key_naming_a_declared_parameter_is_refused,
    test_a_validator_field_and_a_target_read_are_declared_parameters_too).
    Refusing is the end that can be relaxed later without breaking a caller.
    Two kinds of key name one and stand: an ``UNSET`` entry, which supplies
    nothing (test_an_unset_entry_naming_a_declared_parameter_is_dropped_not_refused),
    and a parameter the spec's own typed ``kwargs`` provider fills, whose
    caller's value is dropped before any check and whose overlay value is
    dropped beneath the provider, so nothing diverges
    (test_a_parameter_the_spec_s_typed_provider_fills_is_not_refused). A
    key naming no parameter is the overlay's to add, and stands
    (test_the_spec_s_kwargs_provider_outranks_the_overlay); each of the three
    parts of the set expression below is held by the test named for it here.
    """
    keys = provider_keys(spec.kwargs)
    owned = keys.filled if keys is not None else frozenset()
    supplied = {name for name, value in overlay.kwargs.items() if value is not UNSET}
    taken = sorted((supplied & declared.names()) - owned)
    if taken:
        raise ImproperlyConfigured(
            f"extra_kwargs names the parameter(s) {taken}, which the {type(spec).__name__} "
            "declares. A caller's value for a parameter is what the permission checks and the "
            "target selector see, so an overlay may not stand in for it; rename the key, or "
            "fill it from the spec's typed kwargs provider."
        )


def overlaid(
    overlay: Mapping[str, Any],
    provided: Mapping[str, Any],
    provider: Callable[..., Any] | None,
    *,
    label: str,
    reserved: frozenset[str],
) -> dict[str, Any]:
    """``overlay`` beneath ``provided``, what the spec's own ``provider`` answered.

    The provider outranks the overlay on a clash, as djangorestframework-services
    puts a view's hooks before the spec's provider
    (test_the_spec_s_kwargs_provider_outranks_the_overlay). Treated as the
    provider's own answer is: a key whose value is ``UNSET`` is declined, so
    a value beneath it stands
    (test_an_unset_entry_naming_a_declared_parameter_is_dropped_not_refused),
    and a key named in ``reserved`` is refused, as ``provide`` refuses it.
    A key the provider is annotated to fill, and may not decline, is the
    provider's alone, so the overlay's value for it is dropped: a provider
    that leaves it out leaves it absent rather than the overlay's
    (test_a_key_the_spec_s_typed_provider_owns_is_never_the_overlay_s), and
    one that may decline it lets the overlay's through
    (test_a_key_the_provider_may_decline_falls_to_the_overlay).
    """
    taken = sorted(overlay.keys() & reserved)
    if taken:
        raise ImproperlyConfigured(
            f"{label} returned the key(s) {taken}, which dispatch seeds itself. A "
            "provider's value must never outrank a seeded one; rename the key."
        )
    keys = provider_keys(provider)
    owned = keys.filled if keys is not None else frozenset()
    kept = {key: value for key, value in overlay.items() if value is not UNSET and key not in owned}
    return {**kept, **provided}


# Named in shaping's misconfiguration error, so it points at the declaration to
# fix rather than at "a selector" of which a service spec may carry three.
SELECTOR_SOURCE = "SelectorSpec.selector"
INSTANCE_SOURCE = "ServiceSpec.instance_selector_spec.selector"
COLLECTION_SOURCE = "ServiceSpec.collection_selector_spec.selector"
OUTPUT_SOURCE = "ServiceSpec.output_selector_spec.selector"


@dataclass(frozen=True)
class Prepared:
    """A service spec that has passed every step before its run.

    What crosses from the prelude to the run, and from the run to the output
    selector: ``adispatch`` returns it from one executor hop and may hand it to
    another, so everything the later phases read is here rather than recomputed.
    """

    principal: Any
    target: Any
    # The Validator's ``data``: a mapping, or the instance a dataclass one builds.
    data: Any
    kwargs: dict[str, Any]
    # The call's base pool, read-only: what the Validator's context and the
    # presenter's carry as ``ambient``.
    ambient: Mapping[str, Any]


@dataclass(frozen=True)
class _CheckedRows:
    """A ``many`` spec's list after the shape check: each row's checked arguments, or its refusal.

    Carried in the checked arguments under ``many_argument`` rather than
    raised, so the Validator's refusals of the other rows join the same tree:
    every failing row is reported at once, as DRF's ``ListSerializer`` reports
    them. Both mappings are keyed by the row's ``int`` index.
    """

    rows: dict[int, dict[str, Any]]
    errors: dict[int, Any]


def checks_arguments(checked: Mapping[str, Any]) -> Mapping[str, Any]:
    """What a permission check that declares ``arguments`` is handed: ``checked``, as a read-only mapping.

    The shape-checked arguments the call carries, less a ``many`` call's
    rows: they are refused or validated in step five, after every check, so
    a check would be deciding on rows nobody has validated, and the carrier
    they travel in is dispatch's own
    (test_a_many_call_s_checks_are_handed_its_reads_and_never_its_rows). A
    copy of the top level behind a proxy, so a check can neither add nor
    remove an argument; the values are the call's own objects, not copies,
    so a check must not mutate them
    (test_the_mapping_is_read_only_at_its_top_level_and_its_values_are_the_call_s).
    """
    return MappingProxyType(
        {name: value for name, value in checked.items() if not isinstance(value, _CheckedRows)}
    )


def open_call(
    spec: ServiceSpec | SelectorSpec,
    principal: Any,
    arguments: Mapping[str, Any],
    *,
    grant: Grant | None,
    pool_seeds: PoolSeeds,
    unknown_arguments: UnknownArguments,
    parameters: Parameters | None = None,
    settle_rows: bool = False,
    overlay: Overlay = NO_OVERLAY,
) -> tuple[dict[str, Any], Grant]:
    """Steps one and two: the checked arguments, and the grant the call runs under.

    The one prelude: ``dispatch``, ``adispatch`` and ``resolve_target`` call
    it, and so does ``check_call``, its public face, so a transport that checks
    a call before enqueueing it and the dispatch that later runs it cannot
    refuse different calls.

    ``parameters`` is what is checked, ``spec.parameters()`` unless given:
    ``resolve_target`` checks its target selector's alone.

    ``settle_rows`` is for a caller with no step five to come, ``check_call``:
    a ``many`` call's rows, which the shape check carries to the Validator's
    step rather than raising, are raised here instead, after the permission
    check and in the tree step five raises them in, and otherwise handed back
    as the list of checked rows. Without it they stay carried, for
    ``validate_arguments`` to report beside the Validator's own refusals.

    **A deactivated principal is refused before anything else**, as
    ``PrincipalUnavailable``, by the rule ``resolve_principal`` and the HTTP
    entry points read too: an authenticated principal whose ``is_active`` is
    false, where one with no ``is_active`` reads as active and anonymous goes on
    to the permission check. First, so the three ways a principal reaches
    dispatch - handed over, named by ``principal_id``, or ``request.user`` -
    are refused at the same point and learn nothing about their arguments. A
    ``grant`` does not stand in for it: a grant says the permission check ran,
    and whether there is anyone to check is a question before that.

    A parameter a registered seed occupies is refused next, before the
    arguments are looked at, because it is the declaration that is wrong and it
    is wrong for every caller. The dispatcher's own names never reach this
    check: ``spec.parameters()`` refuses them as it assembles. A registered
    seed is the project's, so only dispatch - which is handed the registry -
    can see the collision. So is an ``overlay`` key naming a declared
    parameter, for the same reason (see ``refuse_overlaid_parameters``).

    Class-level authorization runs before anything is resolved, so a principal
    it refuses learns nothing about which rows exist. It runs after the shape
    check, which reveals only what the declaration already says.
    """
    if is_deactivated(principal):
        raise PrincipalUnavailable()
    # Against the spec's whole parameters, whatever ``parameters`` narrows the
    # shape check to: the declaration is wrong for every caller, so
    # ``resolve_target`` refuses it as dispatch does
    # (test_a_validator_field_a_registered_seed_occupies_is_refused_as_dispatch_refuses_it).
    declared = spec.parameters()
    taken = sorted(declared.names() & pool_seeds.reserved)
    if parameters is None:
        parameters = declared
    if taken:
        raise ImproperlyConfigured(
            f"{type(spec).__name__} declares the parameter(s) {taken}, which a registered "
            "pool seed occupies. An argument must never meet a seed in one pool; rename "
            "the parameter."
        )
    refuse_overlaid_parameters(spec, declared, overlay)
    checked = shape_check(spec, parameters, arguments, unknown_arguments=unknown_arguments)
    granted = authorize(spec, principal, grant=grant, arguments=checks_arguments(checked))
    if settle_rows:
        # Only a ``many`` spec's list is ever carried as ``_CheckedRows``: a
        # refused row raises as step five raises it
        # (test_a_many_spec_s_refused_rows_are_raised_as_dispatch_raises_them),
        # and the rows come back as a list rather than as dispatch's carrier
        # (test_a_many_spec_s_rows_come_back_as_a_list_of_checked_rows).
        for name, value in checked.items():
            if isinstance(value, _CheckedRows):
                if value.errors:
                    raise InvalidArguments({name: dict(sorted(value.errors.items()))})
                checked[name] = [value.rows[index] for index in sorted(value.rows)]
    return checked, granted


def shape_check(
    spec: ServiceSpec | SelectorSpec,
    parameters: Parameters,
    arguments: Mapping[str, Any],
    *,
    unknown_arguments: UnknownArguments,
) -> dict[str, Any]:
    """``check_arguments`` over ``parameters``, leaving out what the server will fill anyway.

    One function for ``open_call``, ``resolve_target`` and ``bind_arguments``,
    so a transport that binds for itself relaxes exactly what dispatch
    relaxes. Two things are relaxed:

    - **A parameter a typed provider is annotated to fill**, which is always
      one that provider's values reach (see ``_server_filled``): not
      demanded of the caller, since it is the server's:
      ``server_owned_keys`` tells a transport to hide exactly such a key.
      **A value the caller sends for it anyway is checked as declared, then
      dropped** from what this returns, so it reaches no merge and the
      provider's answer is the only one
      (test_a_server_owned_key_the_provider_leaves_out_is_never_the_caller_s).
      It is still required of the merged result: a
      provider that declines it after all, with ``UNSET`` or by leaving it
      out, leaves the key absent rather than the caller's, and the usual
      refusal to the step that reads it - the
      Validator for one of its fields
      (test_a_filled_field_the_provider_declines_is_refused_by_the_validator),
      ``call_keywords`` for a read the service or a selector asks for
      (test_a_filled_read_the_provider_declines_is_refused_where_the_service_asks_for_it,
      test_a_target_read_the_lookup_s_provider_declines_is_refused_where_the_selector_asks),
      whether or not the caller sent it
      (test_a_filled_read_the_caller_sends_is_refused_where_the_service_asks_if_the_provider_declines).
      djangorestframework-services drops the caller's value for a
      server-owned key at every site that spreads caller input, and this is
      that rule.
    - **Under** ``partial`` **an absent Validator field**, at any depth, as
      djangorestframework-services relaxes only its serializer. A ``reads``
      argument and a target selector's read, the ``pk`` among them, stay
      required as declared unless a provider fills them: a partial update
      still needs to say which row it updates
      (test_a_partial_call_omitting_the_target_s_pk_is_refused_at_the_shape_check).

    A present value is checked as declared either way, and an unknown key is
    still refused
    (test_a_relaxed_read_the_caller_sends_is_still_checked_and_the_provider_outranks_it).

    **On a** ``many`` **spec the Validator's parameters are each row's**, so
    the Validator's relaxings apply inside every row and none at the top
    level, where the list stays required and a read is relaxed only as a
    provider fills it (test_partial_leaves_the_list_and_the_reads_required,
    test_a_many_spec_s_read_its_kwargs_provider_fills_is_not_demanded_of_the_caller).
    The list's own refusal - absent, null, not a list - and the top level's
    are raised here; each row's is carried to ``validate_arguments`` as
    ``_CheckedRows``, to be reported with the Validator's.
    """
    reads = _server_filled(spec)
    # The schema relaxes ``partial`` through the same function, so the two
    # cannot disagree about which fields a partial call may leave out.
    parameters = relax_partial(spec, parameters)
    # One arc to coverage, each conjunct held by bind_arguments' tests:
    # test_a_selector_spec_returns_its_checked_arguments (the first: a selector
    # spec has no ``validator``) and
    # test_a_service_spec_with_no_validator_checks_its_target_reads_and_returns_nothing.
    if isinstance(spec, ServiceSpec) and spec.validator is not None:
        fields = _filled(spec.input_data, spec.validator.parameters())
        if spec.many:
            return _check_bulk(
                _relaxed(parameters, reads),
                arguments,
                name=spec.many_argument,
                unknown_arguments=unknown_arguments,
                owned=reads,
                owned_in_rows=fields,
            )
        reads |= fields
    return _without(
        check_arguments(
            _relaxed(parameters, reads), arguments, unknown_arguments=unknown_arguments
        ),
        reads,
    )


def relax_partial(spec: ServiceSpec | SelectorSpec, parameters: Parameters) -> Parameters:
    """``parameters`` as a call of ``spec`` is checked under ``partial``: every Validator parameter optional.

    The one reading of what a partial call may leave out, for the shape check
    and for ``spec_input_schema``'s ``required``, so the schema never asks for
    a field dispatch would not refuse absent, nor leaves one out that it
    would. Made optional at every depth - an object's fields and an array's
    rows included - as djangorestframework-services relaxes only its
    serializer. The spec's ``reads`` and its target selector's keep their
    ``required``: a partial update still names the row it updates
    (test_a_partial_call_omitting_the_target_s_pk_is_refused_at_the_shape_check).
    On a ``many`` spec the Validator's parameters are each row's, so the list
    stays required and only its rows are walked, since a read may share a
    row field's name
    (test_a_partial_many_spec_requires_the_list_and_its_reads_and_nothing_in_a_row).

    ``parameters`` as they are for a selector spec, which has no ``partial``,
    and for a service spec that is not partial. One branch to coverage, so
    each condition is held by its own test:
    test_a_selector_specs_schema_is_its_reads (the type: without it, a
    selector spec's missing attribute raises) and
    test_a_spec_that_is_not_partial_requires_every_required_parameter (the
    flag). The Validator's are told apart by what they are not, the spec's
    reads and its target's, so the Validator is not asked for its parameters
    again; a read and a Validator parameter of one name are refused when
    ``parameters()`` is assembled. Of the names kept, the spec's reads are
    held by test_a_partial_spec_with_no_target_keeps_its_reads_required and
    the target's by
    test_a_partial_spec_requires_none_of_its_validators_parameters_at_any_depth.

    A copy, so the declaration every other reader sees - ``parameters()``
    itself, which still says what a whole call needs - is untouched.
    """
    if not (isinstance(spec, ServiceSpec) and spec.partial):
        return parameters
    if spec.many:
        return Parameters.of(
            *(_below(param) if param.name == spec.many_argument else param for param in parameters)
        )
    target = spec.target_selector_spec()
    kept = spec.reads.names() | (target.parameters().names() if target is not None else frozenset())
    return Parameters.of(
        *(param if param.name in kept else _optional(param) for param in parameters)
    )


def _without(checked: dict[str, Any], owned: frozenset[str]) -> dict[str, Any]:
    """``checked`` less every key a typed provider fills: the caller's value for one is never used.

    Checked first, so a value the caller sends is held to its declaration as
    any other is. Then dropped, so it reaches no merge: a provider that
    answers the key outranks nothing, and one that omits it or returns
    ``UNSET`` leaves the key absent rather than the caller's, to be refused
    where it is read. Otherwise a ``total=False`` provider - one that fills a
    tenant for the users who have one - would hand the caller the choice for
    everyone else.
    """
    return {name: value for name, value in checked.items() if name not in owned}


def _server_filled(spec: ServiceSpec | SelectorSpec) -> frozenset[str]:
    """The reads a typed ``kwargs`` provider fills where its values reach them: no caller's to send.

    **A provider relaxes only the parameters its values reach**, so a key it
    is annotated to fill is relaxed where the callable reading it is called
    with the provider's value:

    - A selector's own ``kwargs`` is merged over its ``reads`` in
      ``selector_pool``, so it relaxes that selector's reads: a selector
      spec's
      (test_a_selector_spec_s_read_its_kwargs_provider_fills_is_not_demanded_of_the_caller),
      and a service spec's target selector's
      (test_a_target_read_the_lookup_s_kwargs_provider_fills_is_not_demanded_of_the_caller).
    - A service spec's ``kwargs`` is merged into the service's pool after
      the caller's ``reads``, so it relaxes the spec's ``reads``
      (test_a_read_the_spec_s_kwargs_provider_fills_is_not_demanded_of_the_caller).
    - ``input_data`` is merged into the Validator's arguments alone, so it
      relaxes the Validator's fields, in ``shape_check``.

    A filled key naming a parameter in any other seat - a read named by
    ``input_data``, a target read or a Validator field named by the spec's
    ``kwargs``, a spec read or a Validator field named by the target
    selector's ``kwargs`` - is refused by ``ServiceSpec`` before any call
    reaches here, so every name ``server_owned_keys`` lists that a parameter
    declares is one this relaxes. The rule is still read per provider rather
    than as that union, so the relaxing never outruns the delivery.

    Only ``filled`` keys: a ``declinable`` one stays the caller's, required
    of the caller as declared and kept when the provider declines it
    (test_a_declinable_key_stays_required_of_the_caller,
    test_a_declinable_key_stays_the_caller_s). And a
    provider whose return says nothing about its keys relaxes nothing
    (test_an_untyped_kwargs_provider_relaxes_no_read).
    """
    if isinstance(spec, SelectorSpec):
        return _filled(spec.kwargs, spec.reads)
    target = spec.target_selector_spec()
    lookup = frozenset() if target is None else _filled(target.kwargs, target.reads)
    return lookup | _filled(spec.kwargs, spec.reads)


def _filled(provider: Callable[..., Any] | None, parameters: Parameters) -> frozenset[str]:
    """The names in ``parameters`` that ``provider`` is annotated to fill; none if it does not say."""
    keys = provider_keys(provider)
    return parameters.names() & keys.filled if keys is not None else frozenset()


def _check_bulk(
    parameters: Parameters,
    arguments: Mapping[str, Any],
    *,
    name: str,
    unknown_arguments: UnknownArguments,
    owned: frozenset[str],
    owned_in_rows: frozenset[str],
) -> dict[str, Any]:
    """The top level of a ``many`` call checked here, and each row checked on its own.

    Each row is the list's own ``items``, as ``relax_partial`` left them,
    with what ``input_data`` fills relaxed on top. ``owned`` is what a typed
    ``kwargs`` provider fills at the top level and ``owned_in_rows`` what
    ``input_data`` fills in each row: dropped from each once checked (see
    ``_without``).

    A list is checked at the top level as an empty one, so the list itself
    and every argument beside it are checked as declared while no row is: a
    row checked there would raise with the others, before the Validator could
    add its own refusals of the rest. Its length is read on the list as sent,
    and the empty stand-in is held to no minimum, or ``many_min_length=1``
    would refuse every call
    (test_many_min_length_is_the_rule_an_empty_list_is_refused_by). Anything
    that is not a list, or a list of a length it does not take, is checked as
    it was sent, and refused: the length at the list itself, before any row is
    read, beside the top level's other refusals
    (test_a_list_past_its_maximum_is_refused_beside_the_top_level_s_own_refusals).
    """
    value = arguments.get(name) if isinstance(arguments, Mapping) else None
    the_list = next(param for param in parameters if param.name == name)
    # A ``many`` spec's list is built with the Validator's parameters as its
    # rows (``ServiceSpec.parameters``), never a JSON type or nothing.
    rows = _relaxed(cast(Parameters, the_list.items), owned_in_rows)
    # One branch to coverage, each condition held by its own test:
    # test_the_list_s_own_refusal_is_a_list_under_its_name (the type: without
    # it, a value that is no list is measured and read as rows) and
    # test_a_list_of_rows_past_the_default_maximum_is_refused_at_the_list (the
    # length: without it, every row is checked and validated first).
    if not isinstance(value, (list, tuple)) or length_problem(the_list, len(value)) is not None:
        return check_arguments(parameters, arguments, unknown_arguments=unknown_arguments)
    stand_in = Parameters.of(
        *(replace(param, min_length=None) if param is the_list else param for param in parameters)
    )
    checked = _without(
        check_arguments(stand_in, {**arguments, name: []}, unknown_arguments=unknown_arguments),
        owned,
    )
    cleaned: dict[int, dict[str, Any]] = {}
    errors: dict[int, Any] = {}
    for index, row in enumerate(value):
        # Each row as a top-level call, which is how the shape check reads a
        # row nested in a declared array too: the same unknown-key policy, and
        # a row that is no object refused under ``non_field_errors``.
        try:
            cleaned[index] = _without(
                check_arguments(rows, row, unknown_arguments=unknown_arguments), owned_in_rows
            )
        except InvalidArguments as refused:
            errors[index] = refused.detail
    checked[name] = _CheckedRows(cleaned, errors)
    return checked


def _relaxed(parameters: Parameters, filled: frozenset[str]) -> Parameters:
    """``parameters`` with the ones a typed provider fills optional, at the top level only.

    A copy, made for the shape check alone, so the declaration every other
    reader sees - the schema, ``required`` - is untouched. Only the top
    level, because a provider fills a whole argument, never a field inside one.
    """
    return Parameters.of(
        *(replace(param, required=False) if param.name in filled else param for param in parameters)
    )


def _optional(param: Parameter) -> Parameter:
    """``param`` and everything declared below it made optional, as a partial serializer reads it."""
    return replace(_below(param), required=False)


def _below(param: Parameter) -> Parameter:
    """``param`` with everything declared below it optional: an object's fields, an array's rows."""
    items = param.items
    return replace(
        param,
        fields=None if param.fields is None else Parameters.of(*map(_optional, param.fields)),
        items=Parameters.of(*map(_optional, items)) if isinstance(items, Parameters) else items,
    )


def selector_pool(
    selector_spec: SelectorSpec,
    checked: Mapping[str, Any],
    *,
    principal: Any,
    pool_seeds: PoolSeeds,
    progress: ProgressReporter | None = None,
    extra_kwargs: Mapping[str, Any] = MappingProxyType({}),
) -> dict[str, Any]:
    """The pool a selector is called from: the base pool, its ``reads``, then its ``kwargs``.

    Only its own reads. A service spec's checked arguments also carry its
    Validator's, which have not been validated yet and are not the selector's
    to see. The spec's ``kwargs`` provider is called from the base pool and
    those reads, and what it returns is merged after them, so a key it answers
    is the author's whatever the caller sent: on a target selector it scopes
    the lookup (test_a_target_selector_s_kwargs_provider_scopes_the_lookup).
    A read it is annotated to fill never carries the caller's value here at
    all: ``shape_check`` dropped it, so a provider that leaves it out leaves
    it absent.

    ``progress`` is passed only for a selector spec's own selector, which is
    that spec's run (see ``call_pool``), and is the pool's ``progress``, as
    it is a service's. The spec's ``progress_reporter`` is not joined here:
    only the run hears it, joined to its keywords by ``with_run_progress``
    once they are bound, as a service's run is. A nested selector declaring
    one is refused when the service spec is built.

    ``extra_kwargs`` is the call's overlay, merged beneath the ``kwargs``
    provider's answer (see ``overlaid``); only a selector spec's own selector
    is handed one, never a service spec's target selector.
    """
    reads = selector_spec.reads.names()
    base = base_pool(user=principal, progress=progress, seeds=pool_seeds)
    pool = {**base, **{name: value for name, value in checked.items() if name in reads}}
    pool.update(
        overlaid(
            extra_kwargs,
            provide(
                selector_spec.kwargs,
                pool,
                label="SelectorSpec.kwargs",
                reserved=pool_seeds.reserved,
            ),
            selector_spec.kwargs,
            label="extra_kwargs",
            reserved=pool_seeds.reserved,
        )
    )
    return pool


def with_run_progress(
    selector_spec: SelectorSpec,
    kwargs: dict[str, Any],
    pool: Mapping[str, Any],
    *,
    reserved: frozenset[str],
    transport: ProgressReporter | None,
) -> dict[str, Any]:
    """A selector spec's run keywords, with the run's reporter under ``progress`` where it takes one.

    Called once ``kwargs`` are bound, which is the last step before a
    selector spec's run that can refuse the call: ``call_keywords`` refusing
    a read the caller left out. So an ``async def`` selector, whose provider
    is resolved before the run rather than on its first report, never calls
    it for a call refused there
    (test_an_async_selector_refused_its_missing_read_never_calls_the_progress_provider).
    And only where the selector takes ``progress``, as ``prepare_service``
    does for a service, so one that could never report never calls it
    (test_an_async_selector_that_takes_no_progress_never_calls_the_progress_provider).

    The provider is called from the base pool, as a service spec's is: the
    entries of ``pool`` under a seeded name, which are exactly
    ``base_pool``'s, since no read and no provided key may take one
    (test_a_selector_spec_s_progress_provider_is_called_from_the_base_pool).
    """
    if "progress" not in kwargs:
        return kwargs
    base = {name: value for name, value in pool.items() if name in reserved}
    reporter = run_progress(
        selector_spec.progress_reporter, selector_spec.selector, base, transport=transport
    )
    return {**kwargs, "progress": reporter}


def provide(
    provider: Callable[..., Any] | None,
    pool: Mapping[str, Any],
    *,
    label: str,
    reserved: frozenset[str],
) -> dict[str, Any]:
    """A ``kwargs`` provider's entries, refusing one that names a key dispatch seeds.

    The provider's values are merged after the caller's on purpose, so it can
    outrank an argument; it must never outrank a seed. A provider returning
    ``user`` would run the operation as whoever it named, and one returning
    ``data`` or ``instance`` would replace what the Validator validated or
    the row the object-level check passed. Refused rather than dropped, as a
    Validator returning one is, so the bug is found.
    """
    provided = resolve_provider(provider, pool, label=label)
    taken = sorted(provided.keys() & reserved)
    if taken:
        raise ImproperlyConfigured(
            f"{label} returned the key(s) {taken}, which dispatch seeds itself. A "
            "provider's value must never outrank a seeded one; rename the key."
        )
    return provided


def run_progress(
    provider: Callable[..., Any] | None,
    run: Callable[..., Any],
    base: Mapping[str, Any],
    *,
    transport: ProgressReporter | None,
) -> ProgressReporter:
    """The reporter ``run`` reports to: the transport's, beside the spec's ``progress_reporter``.

    The provider is called from ``base``, the base pool, and only once a
    report is made, so a call refused before its run never calls it. Except
    for an ``async def`` run, whose reports are made on an event loop, where a
    provider that queries cannot run: that one is resolved now, from sync
    code, which is why every caller of this function calls it only once every
    check before the run that can refuse the call has passed
    (test_an_async_service_s_progress_provider_is_resolved_before_the_run).
    A selector spec's selector is its run, and the checks on what it
    returned - the object-level and scope checks, its ``preconditions`` -
    answer after it, so a selector spec those refuse may already have called
    the provider, on either path; everything that can refuse it before the
    run has answered by then (see ``with_run_progress``). With neither,
    ``null_progress``, as ``base_pool`` seeds it.
    """
    resolve = resolve_progress if is_async(run) else deferred_progress
    reporter = resolve(provider, base, transport=transport)
    return null_progress if reporter is None else reporter


def run_preconditions(
    spec: ServiceSpec | SelectorSpec, pool: Mapping[str, Any], *, fillable: frozenset[str]
) -> None:
    """Call each of ``spec``'s ``preconditions`` from ``pool``, in declaration order.

    Raise-to-abort: the first to raise stops the call, and a return value is
    ignored. Bound as the callable it guards is, through ``call_keywords``
    with the same ``fillable``, since a precondition reads the same pool and
    the caller could fill exactly what the run lets them fill.

    Ignored, except for one still to be awaited. An ``async def`` precondition
    is refused when the spec is built, but a plain ``def`` handing back a
    coroutine - a decorated ``async def``, a lambda calling one - looks sync
    until it answers, and its refusal would sit unraised inside the coroutine
    while the call went ahead. ``sync_result`` refuses that answer, so the
    call fails closed with ``ImproperlyConfigured`` rather than running.
    """
    for precondition in spec.preconditions or ():
        sync_result(
            precondition(**call_keywords(precondition, pool, fillable=fillable)),
            asked=f"The precondition {_name(precondition)}",
            seat="A precondition",
        )


def sync_result(answer: Any, *, asked: str, seat: str) -> Any:
    """Return what a sync-only callable answered, refusing an answer that is still to be awaited.

    For the seats dispatch and ``present`` call from sync code and never await:
    a precondition, whose answer would otherwise be ignored as a pass, and a
    presenter, whose answer would otherwise be handed back as the payload. A
    plain ``def`` returning a coroutine or an async generator - a decorated
    ``async def``, a partial or lambda over one - is not refused when the spec
    is built, so the answer is checked where it is read. ``asked`` names the
    callable and ``seat`` the kind of thing it is, for the message.

    A coroutine is closed first, so it is not left behind to warn that it was
    never awaited. Two disjuncts, each held in ``tests/dispatch/test_utils.py``'s
    ``TestAPreconditionAnsweringWithAnAwaitable``:
    ``test_an_awaitable_that_is_not_a_coroutine_is_refused`` fails without the
    first and ``test_an_async_generator_is_refused`` without the second, since
    an async generator is not awaitable.
    """
    if inspect.isawaitable(answer) or inspect.isasyncgen(answer):
        if inspect.iscoroutine(answer):
            answer.close()
        raise ImproperlyConfigured(
            f"{asked} answered with an awaitable ({type(answer).__name__}). {seat} is "
            "sync-only and is never awaited, so its answer is refused rather than used; "
            "declare it with def."
        )
    return answer


def _name(value: Any) -> str:
    """A callable's qualified name for a message, or its type's name when it has none."""
    return getattr(value, "__qualname__", None) or type(value).__name__


def call_pool(
    principal: Any,
    pool_seeds: PoolSeeds,
    entries: Mapping[str, Any],
    *,
    progress: ProgressReporter | None = None,
) -> dict[str, Any]:
    """The base pool, then this call's own entries on top of it: the output selector's pool.

    ``progress`` is the caller's reporter, and is passed only for a pool a run
    is called from: a service's, or a selector spec's own selector's, which
    ``prepare_service`` and ``selector_pool`` build the same way. A target or
    output selector's pool gets ``base_pool``'s no-op instead, deliberately,
    as djangorestframework-services does: a lookup has no progress to report,
    and one reporting after the service finished would read to a watching
    client as the work having restarted.

    Added after ``base_pool`` returns rather than spread through its
    ``**extra``, for two reasons. Every seed resolves before the entries exist,
    so a resolver sees the principal and never an argument: a seed is ambient,
    and a caller must not steer one by naming an argument after something its
    resolver reads. And ``**extra`` shares a namespace with ``base_pool``'s own
    keywords, so a parameter named ``seeds`` would be a ``TypeError`` there.

    Nothing here overwrites a seed. ``open_call`` refused every parameter a
    seed occupies, ``prepare_service`` every validated, bound or provided key,
    ``provide`` a selector's provided one, and the entries dispatch adds
    itself (``data``, ``instance``, ``collection``, ``result``) are names no
    project can register.
    """
    pool = base_pool(user=principal, progress=progress, seeds=pool_seeds)
    pool.update(entries)
    return pool


def reraise_unless_retrieve(selector_spec: SelectorSpec, error: ObjectDoesNotExist) -> None:
    """Called from an ``except ObjectDoesNotExist``: what that exception means for this selector.

    A RETRIEVE selector written with ``.get()`` says "no such row" by raising,
    and that is the same missing row a ``.filter()`` returning nothing is, so
    it becomes ``None`` and the caller decides between not-found and
    ``allow_none``. A LIST has no missing row: a ``DoesNotExist`` escaping one
    is a fault inside the selector, and passes through untouched.

    One rule, called from the two places a selector can raise it: the sync
    call, and the await ``adispatch`` makes on the event loop.
    """
    if selector_spec.kind is SelectorKind.LIST:
        raise error


def settle(
    selector_spec: SelectorSpec,
    raw: Any,
    pool: Mapping[str, Any],
    *,
    source: str,
    reserved: frozenset[str],
    fillable: frozenset[str],
) -> Any:
    """Shape what a selector returned, answer its affordances, and collapse a RETRIEVE.

    A selector spec's ``affordances`` are answered wherever its selector runs,
    as djangorestframework-services answers them: on a ``QuerySet`` they join
    the spec's own ``annotations`` in the one ``.annotate()`` call the shaping
    makes, before ``extend_queryset`` and before a transport pages the rows, so
    a page's rows carry what the whole list would have. On any other result - a
    list of rows, or a RETRIEVE selector's bare row - the rows are answered
    after the shaping, by ``rows_with_affordances``. A callable condition is
    answered once, against ``pool`` - the pool the selector was called from -
    with ``reserved``, the call's seed set, so a registered seed reaches it.
    The answers refuse nothing: they describe each row for whoever presents it.

    ``fillable`` is what the selector was bound with, and ``extend_queryset``
    is bound with the same: see ``call_keywords``.

    **A LIST selector's ``None`` under ``allow_none`` is the empty list**, at
    once and before any shaping, since there is no set for ``select_related``
    or an ``annotate`` to apply to. Here rather than in the step that checks
    the rows, because every selector settles through this: a selector spec's
    own on either entry point, a collection target, and a LIST re-read.
    """
    # One arc to coverage, so each conjunct is held by its own test:
    # test_a_list_selector_s_rows_under_allow_none_are_its_rows (the first),
    # test_a_retrieve_selector_s_own_none_under_allow_none_stays_none (the
    # second: a RETRIEVE's ``None`` is a missing row, never an empty list) and
    # test_a_list_selector_s_none_without_allow_none_is_left_as_it_was (the third).
    if raw is None and selector_spec.kind is SelectorKind.LIST and selector_spec.allow_none:
        return []
    if isinstance(raw, BaseManager):
        # ``Note.objects`` is a selector's shortest spelling of every row, and a
        # Manager is neither iterable nor sliceable, so a list declaring no
        # shaping - which leaves the result as it came - could not be presented
        # or paged: test_a_list_selector_returning_a_manager_presents_every_row.
        # ``BaseManager`` rather than ``Manager``, because ``is_queryset``
        # counts every ``BaseManager`` and one built with
        # ``BaseManager.from_queryset`` is not a ``Manager``:
        # test_a_list_selector_returning_a_manager_built_on_base_manager_presents_every_row.
        raw = raw.all()
    annotations: Mapping[str, Any] | None = selector_spec.annotations
    row_conditions: dict[str, Any] = {}
    constants: dict[str, bool] = {}
    queryset = is_queryset(raw)
    if selector_spec.affordances is not None:
        row_conditions, constants = split_affordances(
            selector_spec.affordances, pool, reserved=reserved
        )
        if queryset:
            generated: dict[str, Any] = {
                **{
                    alias: affordance_expression(raw.model, when)
                    for alias, when in row_conditions.items()
                },
                **{
                    alias: Value(answer, output_field=BooleanField())
                    for alias, answer in constants.items()
                },
            }
            # A mapping whose operations declare no conditions generates
            # nothing, and adds no ``annotate`` call:
            # test_a_spec_with_no_affordances_of_its_own_adds_no_annotation.
            if generated:
                annotations = {**(annotations or {}), **generated}
    shaped = apply_shaping(
        raw,
        selector_spec,
        pool,
        annotations=annotations,
        source_label=source,
        fillable=fillable,
    )
    # One branch to coverage, so each condition is held by its own test:
    # test_declaring_nothing_leaves_a_returned_list_as_it_was (the first) and
    # test_every_answer_rides_in_the_one_list_query_and_the_one_annotate_call
    # (the second: a queryset walked here would be answered by a second query).
    if selector_spec.affordances is not None and not queryset:
        shaped = rows_with_affordances(
            shaped,
            kind=selector_spec.kind,
            row_conditions=row_conditions,
            constants=constants,
            source_label=source,
        )
    if selector_spec.kind is SelectorKind.RETRIEVE:
        return materialize_retrieve(shaped)
    return shaped


def lookup(
    selector_spec: SelectorSpec,
    pool: Mapping[str, Any],
    *,
    source: str,
    reserved: frozenset[str],
    after_the_run: bool = False,
    run: bool = False,
    transport: ProgressReporter | None = None,
) -> Any:
    """Call a selector from sync code and settle its return: the rows, the row, or ``None``.

    An ``async def`` selector is bridged by ``run_selector``, driven from this
    thread rather than awaited. That covers a selector spec's own selector when
    sync ``dispatch`` runs it, and a nested one on either entry point: a nested
    selector is never the run, so ``adispatch`` never awaits it on the loop.

    The selector, and its ``extend_queryset``, refuse a read the caller left
    out (see ``call_keywords``); ``after_the_run`` is the output selector's,
    for which nothing is the caller's to fill. Its pool carries no argument,
    so not even a read it declares could be in it, and the service has
    already run: a refusal that reads as "before the run" would tell the
    caller the operation did not happen. A parameter its pool lacks raises as
    the callable's own error.
    test_an_output_selector_is_never_refused_after_the_run (the selector) and
    test_an_output_selector_s_extend_queryset_is_never_refused_after_the_run
    (its ``extend_queryset``) fail without it.

    ``run`` says the selector is a selector spec's own, its run, which alone
    reports to the spec's ``progress_reporter`` beside ``transport``, the
    caller's reporter (see ``with_run_progress``).
    """
    fn = selector_spec.selector
    fillable: frozenset[str] = frozenset() if after_the_run else selector_spec.reads.names()
    kwargs = call_keywords(fn, pool, fillable=fillable)
    if run:
        kwargs = with_run_progress(
            selector_spec, kwargs, pool, reserved=reserved, transport=transport
        )
    try:
        raw = run_selector(fn, kwargs)
    except ObjectDoesNotExist as error:
        reraise_unless_retrieve(selector_spec, error)
        return None
    return settle(selector_spec, raw, pool, source=source, reserved=reserved, fillable=fillable)


def conclude_selector(
    spec: SelectorSpec,
    value: Any,
    *,
    principal: Any,
    grant: Grant,
    pool: Mapping[str, Any],
    reserved: frozenset[str],
    checked: Mapping[str, Any],
) -> DispatchResult:
    """Step four for a selector spec, its ``preconditions``, and its result.

    The object-level check runs on a retrieved row and never on a list: a
    collection has no single object to check against. A list is asked of
    ``has_scope_permission`` instead, through ``authorize_scope``, empty or
    not, as djangorestframework-services guards the resolved set. A ``None``
    that ``allow_none`` let through is asked of neither, as there: it is not a
    row anyone could be refused, nor a set
    (test_a_retrieve_selector_spec_s_none_under_allow_none_is_asked_nothing).

    The ``preconditions`` run last, from the selector's ``pool`` with the rows
    as ``collection`` or the row as ``instance``, as djangorestframework-services
    runs them: after the object-level check, so a principal refused the row is
    never told what a rule over it says
    (test_a_retrieve_selector_spec_s_preconditions_never_run_on_a_row_the_principal_is_refused).
    Never without a row, missing or
    ``None`` under ``allow_none``
    (test_a_selector_spec_s_preconditions_never_run_without_a_row).

    **A** ``target_checked`` **grant covers nothing here**, as it covers
    nothing on a service spec's lookup. It says the checks ran on the target
    its transport found, and a selector spec takes no ``target=`` to hand
    that target over, so the row or set its selector finds from the
    arguments may be one the grant never saw; the checks run on what was
    found, whatever the grant says. The grant still stands for the
    class-level check it was minted for
    (test_a_grant_that_checked_a_target_does_not_cover_the_row_a_selector_spec_finds,
    test_a_grant_that_checked_a_target_does_not_cover_the_set_a_selector_spec_reads).

    The result's presentation context carries the pool's seeds alone, the
    names in ``reserved``: a selector's pool also holds its reads, its
    ``kwargs`` provider's keys and the caller's ``extra_kwargs``, which are
    arguments rather than the call's surroundings
    (test_a_retrieve_s_context_holds_the_seeds_and_never_its_reads_provider_or_overlay,
    which fails with the whole pool handed over).

    ``checked`` is the call's shape-checked arguments, handed to a check that
    declares ``arguments`` as step two handed them.
    """
    grant = replace(grant, target_checked=False)
    handed = checks_arguments(checked)
    fillable = spec.reads.names()
    context = PresentationContext(
        principal,
        ambient=MappingProxyType({name: entry for name, entry in pool.items() if name in reserved}),
    )
    if spec.kind is SelectorKind.LIST:
        authorize_scope(spec, principal, value, grant=grant, arguments=handed)
        run_preconditions(spec, {**pool, "collection": value}, fillable=fillable)
        return DispatchResult(kind="list", value=value, context=context)
    if value is not None:
        authorize_target(spec, principal, value, grant=grant, arguments=handed)
        run_preconditions(spec, {**pool, "instance": value}, fillable=fillable)
    elif not spec.allow_none:
        return NOT_FOUND
    return DispatchResult(kind="instance", value=value, context=context)


def walk_target(
    spec: ServiceSpec,
    principal: Any,
    checked: Mapping[str, Any],
    *,
    grant: Grant,
    pool_seeds: PoolSeeds,
    target: Any = UNSET,
) -> dict[str, Any] | DispatchResult:
    """Steps three and four for a service spec: its target, found and checked.

    The one walk ``prepare_service`` and ``resolve_target`` both run once the
    call is admitted, so a target resolved ahead of the call is the target
    dispatch would have found. Returns the pool's entry for it - ``instance``
    for an instance selector, ``collection`` for a collection one, nothing
    for a create - or ``NOT_FOUND``.

    - **A row**: ``authorize_target``, its ``has_object_permission``.
    - **A missing row**: ``NOT_FOUND`` unless the selector says
      ``allow_none``; then ``authorize_scope`` of ``None``, as
      djangorestframework-services asks its guard of the ``None`` it lets
      through.
    - **A collection**, empty or not: ``authorize_scope`` of the set.
    - **A create**, which resolves nothing: ``authorize_scope`` of ``None``.

    Each is handed ``checked`` for a check that declares ``arguments``, as
    step two was.

    ``target``, when given, is the target a caller resolved itself, and stands
    in for the lookup alone: the checks above still run on it, unless
    ``grant.target_checked`` says they ran already. A create takes ``None``
    there and nothing else, since it has no target to stand in for.

    **A** ``target_checked`` **grant is honoured only with a** ``target``.
    It says the checks ran on the target the caller found, and that is the
    target only when the caller hands it over: a lookup this walk runs itself
    finds whatever the arguments name, which may be another principal's row
    the grant never saw. So without ``target`` the checks run on what was
    found, whatever the grant says
    (test_a_grant_that_checked_another_row_does_not_cover_the_row_dispatch_finds,
    test_a_grant_that_checked_the_target_skips_the_scope_check_only_for_a_target_handed_in).
    """
    if target is UNSET:
        grant = replace(grant, target_checked=False)
    handed = checks_arguments(checked)
    instance_spec = spec.instance_selector_spec
    collection_spec = spec.collection_selector_spec
    # The target lookups get no live reporter, and nor does the output selector
    # in ``finish_service``: neither is the run (see ``call_pool``).
    if instance_spec is not None:
        if target is UNSET:
            pool = selector_pool(instance_spec, checked, principal=principal, pool_seeds=pool_seeds)
            target = lookup(
                instance_spec, pool, source=INSTANCE_SOURCE, reserved=pool_seeds.reserved
            )
        if target is not None:
            authorize_target(spec, principal, target, grant=grant, arguments=handed)
        elif not instance_spec.allow_none:
            return NOT_FOUND
        else:
            authorize_scope(spec, principal, None, grant=grant, arguments=handed)
        return {"instance": target}
    if collection_spec is not None:
        if target is UNSET:
            pool = selector_pool(
                collection_spec, checked, principal=principal, pool_seeds=pool_seeds
            )
            target = lookup(
                collection_spec, pool, source=COLLECTION_SOURCE, reserved=pool_seeds.reserved
            )
        authorize_scope(spec, principal, target, grant=grant, arguments=handed)
        return {"collection": target}
    # One arc to coverage, so each conjunct is held by its own test: a create
    # dispatched with no ``target=`` (test_a_create_asks_the_scope_check_of_nothing)
    # the first, test_a_create_takes_a_pre_resolved_none_and_refuses_a_row the second.
    if target is not UNSET and target is not None:
        raise TypeError(
            "dispatch() was handed a target= for a ServiceSpec that declares no target "
            "selector. A create acts on no existing row; pass target=None or nothing."
        )
    authorize_scope(spec, principal, None, grant=grant, arguments=handed)
    return {}


def refuse_target(spec: ServiceSpec | SelectorSpec, target: Any) -> None:
    """Refuse ``target=`` where nothing is looked up for it to stand in for, before anything runs.

    A selector spec's selector is its run, so a target handed in would stand
    in for the operation itself rather than for a lookup in front of it.
    Refused rather than ignored, since ignoring it runs the selector the
    caller meant to skip. A ``many`` spec's rows are the caller's arguments
    and it resolves no target, so a target there, ``None`` included, stands
    in for nothing; ``resolve_target`` refuses the spec too, so no caller
    holds one to pass.
    """
    if target is UNSET:
        return
    if isinstance(spec, SelectorSpec):
        raise TypeError(
            "target= is a ServiceSpec's, standing in for its target selector's lookup; "
            "a SelectorSpec's selector is its run."
        )
    if spec.many:
        raise TypeError(
            "target= stands in for a target selector's lookup, and a many spec resolves no "
            "target: its rows are the call's arguments."
        )


def validate_arguments(
    spec: ServiceSpec,
    checked: Mapping[str, Any],
    *,
    principal: Any,
    target: Any,
    server_input: Mapping[str, Any],
    ambient: Mapping[str, Any] = MappingProxyType({}),
) -> Validated:
    """Step five: the Validator's whole result, on only the arguments its own ``parameters()`` declare.

    Never the target selector's ``reads`` nor the spec's, which are not the
    Validator's to see (test_a_reads_argument_reaches_the_service_and_never_the_validator).
    ``server_input`` is the spec's ``input_data``, merged over the caller's
    arguments so its values are the author's; a key the Validator does not
    declare is not handed to it, as a serializer ignores a key it has no field
    for. The caller's arguments have been through the shape check, and the
    server's are the author's own values, which the Validator checks.

    ``ValidationContext.partial`` is the spec's ``partial``, and its
    ``ambient`` is ``ambient``: the call's base pool behind a read-only
    proxy, or empty for a caller with no seeds (``bind_arguments``). A spec
    with no
    Validator validates nothing: its ``data`` is ``{}``, and every argument it
    takes is a read.

    **A** ``many`` **spec's Validator is asked once, for the whole list**,
    through ``Validator.validated_many()``: every row the shape check let
    through, under its index, each with ``server_input`` merged over it. What
    it refuses - rows by index, the list itself under ``non_field_errors`` -
    joins the shape check's refusals, and the whole tree is raised as one
    ``InvalidArguments`` under ``many_argument``, so every failing row is
    reported at once. Otherwise its ``Validated`` is the call's: ``values``
    holds the rows' values under ``many_argument`` alone, so no field is
    spread, ``data`` is the list, and ``pool`` is bound once for the call.
    """
    validator = spec.validator
    if validator is None:
        return Validated(values={}, data={})
    declared = validator.parameters().names()
    context = ValidationContext(principal, target, partial=spec.partial, ambient=ambient)
    if spec.many:
        return _validate_rows(
            validator, checked[spec.many_argument], spec.many_argument, context, server_input
        )
    merged = {**checked, **server_input}
    own = {name: value for name, value in merged.items() if name in declared}
    return validator.validated(own, context)


def _validate_rows(
    validator: Validator,
    checked: _CheckedRows,
    name: str,
    context: ValidationContext,
    server_input: Mapping[str, Any],
) -> Validated:
    """``validated_many()`` on the rows the shape check passed, and one refusal for every failing row."""
    declared = validator.parameters().names()
    # Only the keys the Validator declares, as on a single call: a row's own
    # unknown key was refused by the shape check, so only a provider's can
    # reach here (test_each_row_s_validator_sees_only_the_keys_it_declares).
    rows = {
        index: {key: value for key, value in {**row, **server_input}.items() if key in declared}
        for index, row in checked.rows.items()
    }
    try:
        validated = validator.validated_many(rows, context, many_argument=name)
    except InvalidArguments as refused:
        raise InvalidArguments({name: _list_node({**checked.errors, **refused.detail})}) from None
    if checked.errors:
        raise InvalidArguments({name: _list_node(checked.errors)})
    # A row's fields are never spread into the service's keywords, so the
    # list is the only value a many call hands over by name
    # (test_values_spread_beside_the_list_are_refused).
    if validated.values.keys() != {name}:
        raise ImproperlyConfigured(
            f"The Validator's validated_many() returned the value(s) "
            f"{sorted(validated.values)} for a many call; it returns the rows' values under "
            f"{name!r} alone."
        )
    return validated


def _list_node(errors: Mapping[Any, Any]) -> dict[Any, Any]:
    """A list's refusals in reading order: each row by index, then the list's own message.

    A sort key rather than ``sorted(errors.items())``, which cannot compare an
    ``int`` index with ``non_field_errors``
    (test_a_list_level_refusal_sits_beside_the_rows_shape_refusals). Sorted at
    all because the shape check's refusals and the Validator's are merged in
    the order each raised them
    (test_the_refusals_are_in_index_order_whatever_order_the_validator_raised_them_in).
    """
    return dict(
        sorted(
            errors.items(),
            key=lambda item: (0, item[0], "") if isinstance(item[0], int) else (1, 0, str(item[0])),
        )
    )


def prepare_service(
    spec: ServiceSpec,
    principal: Any,
    arguments: Mapping[str, Any],
    *,
    grant: Grant | None,
    pool_seeds: PoolSeeds,
    unknown_arguments: UnknownArguments,
    progress: ProgressReporter | None,
    target: Any = UNSET,
    overlay: Overlay = NO_OVERLAY,
) -> Prepared | DispatchResult:
    """Steps one to six for a service spec, its preconditions, and the keywords its run is called with.

    The target is ``walk_target``'s: found by the target selector, or
    ``target`` when the caller resolved it, then checked - a row by
    ``has_object_permission``, a set or nothing by ``has_scope_permission``.
    Returns ``NOT_FOUND`` when the instance selector resolves nothing and
    ``allow_none`` is off: the service never runs, and neither a provider, the
    Validator nor an affordance is asked. The pool carries ``instance`` when
    the spec declares an instance selector - the row, or ``None`` under
    ``allow_none``, so an upsert's service can declare it without a default -
    and ``collection`` when it declares a collection selector. A create
    carries neither.

    **The service's pool, in the order its entries are merged**, each later
    one outranking an earlier one of the same name:

    1. The base pool: ``user``, ``progress`` and every registered seed.
    2. The validated ``values``, each by name.
    3. The spec's ``reads``, as the caller sent them.
    4. ``data``, the Validator's ``data``, and what else the Validator binds
       for the call (its ``Validated.pool``).
    5. The spec's ``kwargs`` provider, the author's values after the caller's,
       over the call's ``extra_kwargs`` overlay.
    6. ``instance`` or ``collection``.

    No entry outranks a seed: a parameter named after one is refused by
    ``open_call``, and a validated value, a bound value or a provider key
    named after one here, as is a bound value named after a validated value
    or a parameter. A
    read and a Validator parameter of one name are refused when
    ``parameters()`` is assembled, so a read outranks only a value the
    Validator returns without declaring it, as djangorestframework-services'
    route captures outrank the spread body
    (test_a_read_outranks_a_validated_value_of_its_name). The two providers are called from the base pool, the
    ``reads`` and the resolved target, and never see the Validator's values:
    ``input_data`` runs before the Validator, and ``kwargs`` is read the same.
    """
    checked, granted = open_call(
        spec,
        principal,
        arguments,
        grant=grant,
        pool_seeds=pool_seeds,
        unknown_arguments=unknown_arguments,
        overlay=overlay,
    )
    resolved = walk_target(
        spec, principal, checked, grant=granted, pool_seeds=pool_seeds, target=target
    )
    if isinstance(resolved, DispatchResult):
        return resolved
    # The row, the set, or ``None`` for a create: what the Validator's context
    # and the run's result carry.
    target = next(iter(resolved.values()), None)
    reserved = pool_seeds.reserved
    # One base pool for the call, so a seed that queries resolves once for the
    # providers and the service alike. Its ``progress`` is the transport's: the
    # spec's own sink is the run's alone, and joins the run's keywords last.
    base = base_pool(user=principal, progress=progress, seeds=pool_seeds)
    # A copy behind a proxy, so neither the Validator nor the presenter can
    # change the pool the service is called from, or see a later change to it.
    ambient = MappingProxyType(dict(base))
    declared_reads = spec.reads.names()
    reads = {name: value for name, value in checked.items() if name in declared_reads}
    providers_pool = {**base, **reads, **resolved}
    server_input = resolve_provider(spec.input_data, providers_pool, label="ServiceSpec.input_data")
    validated = validate_arguments(
        spec,
        checked,
        principal=principal,
        target=target,
        server_input=server_input,
        ambient=ambient,
    )
    values = validated.values
    # A Validator returning ``user`` is a bug, and letting its value outrank the
    # seed silently would be the worse one: the service would act as whoever
    # the arguments named. Refused rather than dropped, so the bug is found.
    seeded = sorted(values.keys() & reserved)
    if seeded:
        raise ImproperlyConfigured(
            f"The Validator returned the key(s) {seeded}, which dispatch seeds itself. A "
            "validated value must never outrank a seeded one; rename the value."
        )
    # A value bound for the call is not one a caller's argument names, so it
    # may not stand in for a seed, a validated value or a parameter - a read
    # the caller sent, or a field a partial call left out: either way the
    # service would read something other than what its name says. Each set is
    # held by its own case: test_a_bound_value_naming_a_seed_or_a_validated_value_is_refused
    # (``a-seed``; ``an-undeclared-validated-value`` for the values, since
    # ``a-validated-value`` names a parameter too) and
    # test_a_bound_value_naming_a_parameter_is_refused (``a-read``, ``a-field-left-out``).
    named = reserved | values.keys() | spec.parameters().names()
    bound = sorted(validated.pool.keys() & named)
    if bound:
        raise ImproperlyConfigured(
            f"The Validator bound the key(s) {bound}, which dispatch seeds, the Validator "
            "returned as a value, or the spec declares as a parameter. A value bound for "
            "the call needs a name of its own."
        )
    author = overlaid(
        overlay.kwargs,
        provide(spec.kwargs, providers_pool, label="ServiceSpec.kwargs", reserved=reserved),
        spec.kwargs,
        label="extra_kwargs",
        reserved=reserved,
    )
    pool = {
        **base,
        **values,
        **reads,
        "data": validated.data,
        **validated.pool,
        **author,
        **resolved,
    }
    # Before the affordances, as the Validator is: a refusal of the call itself
    # answers before one describing the row's state.
    # test_a_missing_argument_answers_before_an_affordance fails without it.
    # Only the spec's reads and its Validator's parameters reach the service
    # from a caller, and of those only the ones the caller left out are still
    # theirs to fill; with neither, nothing is. A target selector's read was
    # the selector's to consume, never the service's to ask for:
    # test_a_service_parameter_named_after_a_target_read_is_the_author_s_error
    # fails if the spec's whole argument set counts. One the caller sent and the
    # Validator did not hand back under that name - a form popping it in
    # ``clean()``, a pydantic alias returned under the field's name - would be
    # asked for again, forever, by a client reading ``InvalidArguments`` as its
    # own mistake; ``checked`` is exactly what was sent, since the shape check
    # applies no default:
    # test_a_validator_parameter_the_caller_sent_is_the_author_s_error fails
    # without the subtraction. Under ``partial`` no Validator parameter is the
    # caller's to fill, since a partial call may leave out any of them:
    # test_a_partial_call_never_refuses_a_service_parameter_the_caller_left_out
    # holds that conjunct, and every service spec with no Validator dispatched
    # the first, such as
    # test_a_service_parameter_no_validator_declares_is_the_author_s_error. On
    # a ``many`` spec the Validator's parameters are each row's and are never
    # spread, so nothing a caller sends fills one by name:
    # test_a_service_parameter_named_after_a_row_field_is_the_author_s_error
    # holds the third.
    validator = spec.validator
    asked = (
        validator.parameters().names()
        if validator is not None and not spec.partial and not spec.many
        else frozenset()
    )
    fillable = (declared_reads | asked) - checked.keys()
    kwargs = call_keywords(spec.service, pool, fillable=fillable)
    # Step six, in djangorestframework-services' place for it: after the
    # object-level check and the Validator, so a principal who may not see the
    # row is never told what state it is in, and before the run - outside the
    # transaction ``run_service`` opens, so a refusal never opens one. Here
    # rather than in each entry point, so ``adispatch`` answers it inside the
    # same hop as the rest of the prelude: a condition on the row is a query.
    # ``reserved`` is this call's seed set, or a callable condition declaring a
    # registered seed (an HTTP adapter's ``request``) would not be handed it:
    # test_a_condition_reads_a_registered_seed_through_dispatch fails without it.
    # ``instance`` is the row, never a collection: a condition on the row beside
    # a ``collection_selector_spec`` is refused when the spec is declared.
    enforce_affordances(spec, pool, instance=resolved.get("instance"), reserved=reserved)
    # Then the preconditions, still before the run and in the same hop: after
    # the affordances, djangorestframework-services' order
    # (test_an_affordance_answers_before_a_precondition).
    run_preconditions(spec, pool, fillable=fillable)
    # Last, once nothing can refuse the call: the run's reporter, with the
    # spec's own sink beside the transport's. Only for a service that takes
    # ``progress``, so one that never could report never calls the provider.
    if "progress" in kwargs:
        kwargs["progress"] = run_progress(
            spec.progress_reporter, spec.service, base, transport=progress
        )
    return Prepared(principal, target, validated.data, kwargs, ambient)


def finish_service(
    spec: ServiceSpec, prepared: Prepared, result: Any, *, pool_seeds: PoolSeeds
) -> DispatchResult:
    """The output selector, if declared, and the service spec's result.

    The output selector's pool is the base pool plus the service's return,
    as both ``result`` and ``instance``: one value under two names, so a
    re-read written for djangorestframework-services, which binds both, runs
    unchanged. ``instance`` there is never the resolved target, which the
    re-read has no use for: it re-reads what the service produced
    (test_an_output_selector_reads_the_service_s_return_as_instance_not_the_target).
    The arguments are not in it either, for the same reason.

    **A RETRIEVE output selector that finds nothing is ``None``, not
    not-found.** The service has already run, and under ``atomic`` its write
    has committed; reporting not-found would tell the caller the operation did
    not happen. So the value is ``None`` under ``kind="instance"``, whether the
    selector returned nothing or raised ``DoesNotExist``.
    """
    # The row the service changed may carry a prefetch taken before the change:
    # a service that rewrites a relation and returns its target would then be
    # presented with the relation as it was. Only the target is cleared; an
    # output selector's re-read carries its own prefetch on purpose. A
    # collection target has no cache to clear, so the ``getattr`` is a no-op
    # there rather than a type check.
    if getattr(prepared.target, "_prefetched_objects_cache", None):
        prepared.target._prefetched_objects_cache = {}
    output_spec = spec.output_selector_spec
    value = result
    # A ``many`` spec's return is the rows it wrote, presented as a list, as
    # djangorestframework-services renders it; an output selector's kind
    # still decides what its re-read is. A ``None`` it returns stays one
    # value, presented as ``None`` as any service's is: as a list it would be
    # refused by ``present`` after the write had committed. One arc to
    # coverage: test_the_service_runs_once_with_every_validated_row holds the
    # first conjunct, test_a_many_service_returning_none_presents_none the
    # second.
    kind: Literal["instance", "list"] = "list" if spec.many and result is not None else "instance"
    if output_spec is not None:
        # The service's return under both names djangorestframework-services
        # binds it by, so a re-read declares whichever its author wrote:
        # ``instance`` here is what the service returned, not the target it
        # resolved, and it is bound whatever the return is, ``None`` included.
        pool = call_pool(prepared.principal, pool_seeds, {"instance": result, "result": result})
        value = lookup(
            output_spec,
            pool,
            source=OUTPUT_SOURCE,
            reserved=pool_seeds.reserved,
            after_the_run=True,
        )
        kind = "list" if output_spec.kind is SelectorKind.LIST else "instance"
    return DispatchResult(
        kind=kind,
        value=value,
        service_result=result,
        instance=prepared.target,
        data=prepared.data,
        context=PresentationContext(prepared.principal, prepared.target, prepared.ambient),
    )
