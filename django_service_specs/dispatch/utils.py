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
from typing import Any, Final, Literal, cast

from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist
from django.db.models import BooleanField, Value
from django.db.models.manager import BaseManager
from django.http import Http404

from django_service_specs.affordances.enforce_affordances import enforce_affordances
from django_service_specs.affordances.utils import (
    affordance_expression,
    rows_with_affordances,
    split_affordances,
)
from django_service_specs.authorization.utils import (
    QUESTIONS,
    refuse_deactivated,
    seeds_for_checks,
)
from django_service_specs.dispatch.authorize import authorize
from django_service_specs.dispatch.authorize_scope import authorize_scope
from django_service_specs.dispatch.authorize_target import authorize_target
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.grant import Grant
from django_service_specs.dispatch.relax_partial import relax_partial
from django_service_specs.output.presentation_context import PresentationContext
from django_service_specs.parameters.check_arguments import check_arguments
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.parameters.utils import length_problem
from django_service_specs.pool.base_pool import base_pool
from django_service_specs.pool.call_seeds import CALL_SEEDS
from django_service_specs.pool.null_progress import null_progress
from django_service_specs.pool.pool_seeds import PoolSeeds
from django_service_specs.pool.provider_keys import provider_keys
from django_service_specs.pool.utils import (
    deferred_progress,
    only_seeds,
    resolve_progress,
    resolve_provider,
)
from django_service_specs.selectors.is_queryset import is_queryset
from django_service_specs.selectors.materialize_retrieve import materialize_retrieve
from django_service_specs.selectors.run_selector import run_selector
from django_service_specs.selectors.utils import apply_shaping, call_keywords
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.utils import callable_name
from django_service_specs.types.is_async import is_async
from django_service_specs.types.progress_reporter import ProgressReporter
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.types.unknown_arguments import UnknownArguments
from django_service_specs.types.unset import UNSET
from django_service_specs.types.utils import CALL_CONTEXT, CALL_SEEDS_NOTE, SHAPES
from django_service_specs.validation.validated import Validated
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator

NOT_FOUND = DispatchResult(kind="not_found")
"""A required row that does not exist. Frozen, so one instance serves every call."""


class ListNotFound(Exception):
    """A LIST selector's own ``Http404``, raised by ``lookup`` for its caller to answer.

    A LIST has no ``None`` to hand back for a missing row, so ``lookup`` says
    "not found" by raising this, from the selector's ``Http404``. Its own, so
    the caller's ``except`` cannot catch an ``Http404`` from anywhere else in
    the call - ``extend_queryset``, an affordance condition - which passes
    through as it does on ``adispatch``
    (test_an_http404_from_extend_queryset_is_not_the_selector_s_not_found).
    Never raised past dispatch: the selector spec's own run and a write's
    collection selector answer it as ``NOT_FOUND``.
    """


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
    Refused because it is static: whether a key names a declared parameter
    is known from the spec alone, so the same overlay is refused on every
    call, never on some requests and not others.
    """
    owned = _owned(spec.kwargs)
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
    _refuse_seeded(overlay, label=label, reserved=reserved)
    owned = _owned(provider)
    kept = {key: value for key, value in overlay.items() if value is not UNSET and key not in owned}
    return {**kept, **provided}


# Named in shaping's misconfiguration error, so it points at the declaration to
# fix rather than at "a selector" of which a service spec may carry three.
SELECTOR_SOURCE = "SelectorSpec.selector"
INSTANCE_SOURCE = "ServiceSpec.instance_selector_spec.selector"
COLLECTION_SOURCE = "ServiceSpec.collection_selector_spec.selector"
OUTPUT_SOURCE = "ServiceSpec.output_selector_spec.selector"

EVERY_POOL: Final = frozenset({"user", "progress", CALL_CONTEXT, SHAPES}) | CALL_SEEDS
"""What every pool dispatch builds carries, whatever the mount registers.

``base_pool``'s ``user`` and ``progress``, the call's context and the
``shapes`` dispatch adds beside them, and the call's ``request`` and ``view``,
handed to a callable naming either. The keywords ``check_seeds`` and
``unreceived_fields`` count as filled on every mount
(test_every_pool_is_base_pool_s_keys_and_the_call_s_own holds it to
``base_pool``).
"""


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
    # The call's base pool, read-only at its top level, its values the call's
    # own live objects: what the Validator's context and the presenter's carry
    # as ``ambient``.
    ambient: Mapping[str, Any]
    # The transport's dict, the one object every stage was handed, and what
    # the caller sent for the spec's ``shapes``: what the presenter's context
    # carries beside ``ambient``.
    call_context: dict[str, Any]
    shapes: Mapping[str, Any]
    # The seeds a check named, resolved before it: the output selector's pool
    # takes them as they are, as the run's did (see ``seeded_base``).
    early_seeds: Mapping[str, Any]


@dataclass(frozen=True)
class CheckKeywords:
    """What a call offers its permission checks by name besides ``arguments``.

    ``call_context`` is the transport's dict, the one every stage of the call
    is handed. ``seeds`` holds the registered seeds resolved for the checks,
    which ``open_call`` fills before the class-level check and only for a
    spec one of whose checks names one (see ``open_call``); empty otherwise,
    so a check naming none is never handed one. The entry point makes one per
    call and hands it to ``open_call`` and then to step four, so every
    question of the call is offered the same values.
    """

    call_context: dict[str, Any] = field(default_factory=dict)
    seeds: dict[str, Any] = field(default_factory=dict)

    def offered(self) -> dict[str, Any]:
        """The keywords each ``authorize`` function is handed to offer: the context and the seeds."""
        return {"call_context": self.call_context, "seeds": self.seeds}


def shapes_sent(spec: ServiceSpec | SelectorSpec, checked: Mapping[str, Any]) -> Mapping[str, Any]:
    """What the caller sent for ``spec``'s ``shapes``, read-only: the presenter's ``shapes``.

    From the checked arguments, which carry no default, so a shape the caller
    left out is absent rather than ``None``
    (test_shapes_are_read_only_and_an_unsent_one_is_absent), and no argument
    but a declared shape is ever here
    (test_no_other_argument_is_among_the_shapes). A copy behind a proxy, so a
    presenter can neither add nor remove one.
    """
    names = spec.shapes.names()
    return MappingProxyType({name: value for name, value in checked.items() if name in names})


def seeded_base(
    principal: Any,
    *,
    progress: ProgressReporter | None,
    pool_seeds: PoolSeeds,
    early: Mapping[str, Any],
    call_context: Mapping[str, Any],
) -> dict[str, Any]:
    """``base_pool``, taking the seeds already resolved for a check as they are.

    ``early`` holds the seeds a check of the call named, resolved before the
    class-level check (``open_call``). Every pool after takes those values
    rather than resolving them again, so each resolves once per call and the
    check, the selectors and the run see one object
    (test_the_check_and_every_stage_see_the_one_value). The rest resolve here
    as ``base_pool`` resolves them, once per pool. An early value was resolved
    before the run's reporter existed, so its resolver saw ``progress`` as the
    no-op reporter.

    The resolvers bind against a pool carrying ``call_context``, so one
    declaring ``request`` or ``view`` reads the context's
    (test_a_seed_resolved_with_its_pool_reads_the_request), and the context
    leaves the pool before it is returned: it is no seed, and the Validator's
    ``ambient`` is this pool (test_ambient_holds_the_seeds_and_never_the_call_context).
    A seed registered under either name is the value instead, early or not
    (test_the_registered_seed_supplies_the_name).
    """
    seeds = pool_seeds if not early else only_seeds(pool_seeds, pool_seeds.names - early.keys())
    pool = base_pool(user=principal, progress=progress, seeds=seeds, call_context=call_context)
    del pool[CALL_CONTEXT]
    pool.update(early)
    return pool


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
    keywords: CheckKeywords,
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

    **A parameter a registered seed is named like** is answered next, before
    the arguments are looked at, by where it is declared. A registered seed is
    the project's, so only dispatch - which is handed the registry - can see
    the name it shares. The dispatcher's own names never reach here:
    ``spec.parameters()`` refuses them as it assembles. Of the names a
    registered seed shares (see ``split_seed_named``):

    - **A** ``reflected`` **read**, one read off a callable's signature
      rather than written, leaves this call's argument set, and the seed
      fills it in every pool, as it fills a service's parameter of its name
      (test_a_reflected_read_a_registered_seed_is_named_like_is_the_seed_s).
      A caller's value for it meets the rule for any seed's name sent as an
      argument: unknown under ``REJECT``, dropped under ``IGNORE``, and never
      merged over the seed
      (test_a_caller_s_value_for_a_reflected_read_never_reaches_its_callable).
    - **A top-level Validator field** stays an argument of the call, checked
      and validated as declared. ``prepare_service`` keeps its value out of
      the service's pool, where the seed keeps its own, so it reaches the
      service in ``data`` alone
      (test_a_field_named_like_a_registered_seed_validates_into_data_and_the_pool_keeps_the_seed).
    - **Anything else** - a read nobody marked, a shape, a ``many`` spec's
      list - is refused as ``ImproperlyConfigured``, because it is the
      declaration that is wrong and it is wrong for every caller.

    So is an ``overlay`` key naming a declared parameter, for the same reason
    (see ``refuse_overlaid_parameters``).

    Class-level authorization runs before anything is resolved, so a principal
    it refuses learns nothing about which rows exist. It runs after the shape
    check, which reveals only what the declaration already says.

    ``keywords`` is what the call offers its checks by name: its context, and
    the seeds this fills. **Only the registered seeds a check names**, at
    any of its three questions, are resolved here, once, just before the
    class-level check, from a base pool with no live reporter; step four is
    offered the same values, and every pool after takes them as they are
    (``seeded_base``). Every other seed resolves as before - once per pool,
    each after the class-level check - so a resolver that reads the
    principal, ``PoolSeeds``' own ``tenant=lambda *, user: user.tenant``,
    never runs for an anonymous caller a check refuses unless a check names
    that very seed
    (test_a_spec_whose_checks_name_no_seed_resolves_them_exactly_as_before,
    test_an_anonymous_caller_is_refused_before_a_seed_reads_its_principal,
    test_only_the_seeds_a_check_names_resolve_before_it). A resolver raising
    ``PrincipalUnavailable`` here ends the call before any check is asked
    (test_a_seed_raising_principal_unavailable_ends_the_call_before_its_check).
    Every entry point hands its own carrier, one per call, so the walk after
    this is offered the seeds this filled.
    """
    refuse_deactivated(principal)
    # Against the spec's whole parameters, whatever ``parameters`` narrows the
    # shape check to: the declaration is wrong for every caller, so
    # ``resolve_target`` and ``check_call`` answer as dispatch does
    # (test_resolve_target_and_check_call_split_as_dispatch_does, and
    # test_a_validator_field_a_registered_seed_names_resolves_as_dispatch_runs_it
    # for a field, which is outside the target's parameters).
    declared = spec.parameters()
    parameters = seat_seed_named(
        spec, declared, declared if parameters is None else parameters, pool_seeds
    )
    refuse_overlaid_parameters(spec, declared, overlay)
    checked = shape_check(spec, parameters, arguments, unknown_arguments=unknown_arguments)
    # Only the seeds a check names: another seed's resolver may read what an
    # anonymous caller lacks, and this runs before that caller is refused
    # (test_only_the_seeds_a_check_names_resolve_before_it).
    keywords.seeds.update(
        seeds_for_checks(spec, principal, pool_seeds, QUESTIONS, call_context=keywords.call_context)
    )
    granted = authorize(
        spec,
        principal,
        grant=grant,
        arguments=checks_arguments(checked),
        **keywords.offered(),
    )
    if settle_rows:
        # Only a ``many`` spec's list is ever carried as ``_CheckedRows``: a
        # refused row raises as step five raises it
        # (test_a_many_spec_s_refused_rows_are_raised_as_dispatch_raises_them),
        # and the rows come back as a list rather than as dispatch's carrier
        # (test_a_many_spec_s_rows_come_back_as_a_list_of_checked_rows).
        for name, value in checked.items():
            if isinstance(value, _CheckedRows):
                if value.errors:
                    # After step four, which is what the mark says: the grant
                    # ``authorize`` returned above still holds for the caller
                    # (test_a_refused_row_is_marked_as_raised_after_the_class_level_check).
                    raise InvalidArguments(
                        {name: dict(sorted(value.errors.items()))}, after_authorize=True
                    )
                checked[name] = [value.rows[index] for index in sorted(value.rows)]
    return checked, granted


def seat_seed_named(
    spec: ServiceSpec | SelectorSpec,
    declared: Parameters,
    parameters: Parameters,
    pool_seeds: PoolSeeds,
) -> Parameters:
    """``parameters`` less the reads a registered seed fills, refusing a name no seed may share.

    The rule ``open_call`` applies before it looks at the arguments, and
    ``bind_arguments`` given ``pool_seeds`` applies before its shape check, so
    the two answer one declaration alike. ``declared`` is the spec's whole
    parameters, which ``split_seed_named`` reads; ``parameters`` is what is
    checked, narrower for ``resolve_target``. A name ``split_seed_named``
    refuses raises ``ImproperlyConfigured``; a ``reflected`` read it seats
    leaves ``parameters``, so the closed set refuses or drops a caller's value
    for it as for any seed's name. The split reads ``declared`` and the
    narrowing ``parameters``, never the other way about: a name outside what
    this call checks is still refused or seated, and what comes back is never
    wider than what went in
    (test_seat_seed_named_splits_the_whole_spec_and_narrows_only_what_is_checked).
    """
    seated, taken = split_seed_named(spec, declared, pool_seeds)
    if taken:
        raise ImproperlyConfigured(seed_named_refusal(spec, taken, pool_seeds))
    if seated:
        return Parameters.of(*(param for param in parameters if param.name not in seated))
    return parameters


def seed_named_refusal(
    spec: ServiceSpec | SelectorSpec, taken: frozenset[str], pool_seeds: PoolSeeds
) -> str:
    """Why ``spec`` is refused for declaring ``taken``, the second set ``split_seed_named`` returns.

    One wording, read through ``seat_seed_named`` by ``open_call`` on every
    call and by ``bind_arguments`` given seeds, and by ``check_seeds`` at
    registration, so a transport refusing the spec when it registers it
    says what dispatch would have said on its first call
    (test_a_read_a_registered_seed_occupies_is_refused_as_dispatch_refuses_it).
    """
    # The dispatcher's names never get here, so a name no seed registers is
    # one of the call's two, which dispatch fills itself; a read or a shape of
    # either on a service spec is refused when the spec is built, so it is a
    # selector spec's own read or shape, or a ``many`` spec's list
    # (test_a_parameter_named_either_is_refused asserts the hint, and
    # test_a_spec_declaring_a_registered_seed_s_name_is_refused its absence).
    hint = "" if taken <= pool_seeds.names else CALL_SEEDS_NOTE
    return (
        f"{type(spec).__name__} declares the parameter(s) {sorted(taken)}, which a "
        "registered pool seed occupies. An argument must never meet a seed in one pool; "
        f"rename the parameter.{hint}"
    )


def split_seed_named(
    spec: ServiceSpec | SelectorSpec, declared: Parameters, pool_seeds: PoolSeeds
) -> tuple[frozenset[str], frozenset[str]]:
    """Of ``declared``'s names a registered seed shares: the reads it fills, and the ones refused.

    Three ways, which cannot overlap, since ``parameters()`` refuses a name
    two sources declare:

    - a ``reflected`` read - a selector spec's, a target selector's or a
      service spec's - which the seed fills: the first set;
    - a top-level Validator field (``seed_named_fields``), the caller's:
      in neither set;
    - every other name - a read nobody marked, a shape, a ``many`` spec's
      list - refused: the second set
      (test_a_spec_declaring_a_registered_seed_s_name_is_refused,
      test_a_reflected_shape_named_like_a_registered_seed_is_still_refused).
    """
    # The call's ``request`` and ``view`` beside the reserved names: dispatch
    # hands both to every callable naming one, so a parameter of either name is
    # refused on every mount (test_a_parameter_named_either_is_refused fails
    # without the union), and a top-level Validator field of either takes the
    # seat a registered seed's name does
    # (test_a_validator_field_named_request_takes_the_seat fails without the
    # second). ``PoolSeeds.reserved`` itself keeps its published answer, which
    # the transports read.
    shared = declared.names() & (pool_seeds.reserved | CALL_SEEDS)
    seated = shared & frozenset(
        param.name for _, reads in read_seats(spec) for param in reads if param.reflected
    )
    return seated, shared - seated - seed_named_fields(spec, pool_seeds.names | CALL_SEEDS)


def seed_named_fields(spec: ServiceSpec | SelectorSpec, names: frozenset[str]) -> frozenset[str]:
    """The top-level Validator fields of ``spec`` named in ``names``: the caller's, and never the pool's.

    ``names`` is the registered seeds' names; the dispatcher's own never name
    a top-level field, since ``parameters()`` refuses them as it assembles. A
    ``many`` spec's fields are each row's, travel inside the list and are
    never spread, so none is top level. One arc to coverage, each conjunct
    held by its own test: a selector spec has no Validator
    (test_a_reflected_read_a_registered_seed_is_named_like_is_the_seed_s), a
    service spec may have none
    (test_a_caller_s_value_for_a_reflected_read_never_reaches_its_callable[service-sync]),
    and a ``many`` spec's row field shares a name with an unmarked read, which
    stays refused
    (test_a_spec_declaring_a_registered_seed_s_name_is_refused[a-many-spec-s-read-a-row-field-shares]).
    """
    if isinstance(spec, ServiceSpec) and spec.validator is not None and not spec.many:
        return spec.validator.parameters().names() & names
    return frozenset()


def shape_check(
    spec: ServiceSpec | SelectorSpec,
    parameters: Parameters,
    arguments: Mapping[str, Any],
    *,
    unknown_arguments: UnknownArguments,
) -> dict[str, Any]:
    """``check_arguments`` over ``parameters``, leaving out what the server fills or may fill.

    One function for ``open_call``, ``resolve_target`` and ``bind_arguments``,
    so a transport that binds for itself relaxes what dispatch relaxes. The
    seeds are not this function's: its caller hands it ``parameters`` less the
    ``reflected`` reads a registered seed fills (``seat_seed_named``), as
    ``open_call`` does and ``bind_arguments`` does when it is handed
    ``pool_seeds``. Handed none, ``bind_arguments`` checks such a read as
    declared, and a required one is demanded of the caller
    (test_bind_arguments_still_demands_a_required_reflected_read). Two things
    are relaxed:

    - **A parameter a provider fills or may fill**, which is always one that
      provider's values reach (see ``server_filled``): not demanded of the
      caller here, because whether the call has it is known only once the
      provider has answered. It is still required of the assembled pool,
      checked in the seat that merges the provider's answer, after
      class-level authorization: ``selector_pool`` for a selector's reads,
      ``prepare_service`` for a service spec's ``reads``, and
      ``validate_arguments`` for a Validator field, before the Validator runs
      (test_a_filled_field_the_provider_declines_is_refused_before_the_validator,
      test_a_filled_read_the_provider_declines_is_refused_where_the_service_asks_for_it,
      test_a_target_read_the_lookup_s_provider_declines_is_refused_where_the_selector_asks,
      test_a_may_fill_read_nobody_fills_is_refused_at_the_service_seat).
      So a principal the class-level check refuses is told that, rather than
      that such a value is missing
      (test_a_read_an_untyped_provider_may_fill_left_out_reaches_the_class_level_check,
      test_a_declinable_key_left_out_reaches_the_class_level_check).
      **What the caller sends for one depends on the provider's annotation.**
      A key a typed provider is annotated to fill is the server's:
      ``server_owned_keys`` tells a transport to hide exactly such a key, and
      a value the caller sends anyway is checked as declared, then dropped
      from what this returns, so it reaches no merge and the provider's
      answer is the only one
      (test_a_server_owned_key_the_provider_leaves_out_is_never_the_caller_s,
      test_a_filled_read_the_caller_sends_is_refused_where_the_service_asks_if_the_provider_declines).
      djangorestframework-services drops the caller's value for a
      server-owned key at every site that spreads caller input, and this is
      that rule. A key a provider may decline, or any key beside a provider
      whose return names none, is checked and kept, beneath the provider's
      answer, so it stands when the provider declines
      (test_a_declinable_key_stays_the_caller_s,
      test_a_may_fill_read_the_caller_sends_stands_when_an_untyped_provider_leaves_it_out).
    - **Under** ``partial`` **an absent Validator field**, at any depth, as
      djangorestframework-services relaxes only its serializer. A ``reads``
      argument and a target selector's read, the ``pk`` among them, stay
      required as declared unless a provider fills or may fill them: a
      partial update still needs to say which row it updates
      (test_a_partial_call_omitting_the_target_s_pk_is_refused_at_the_shape_check).

    A present value is checked as declared either way, and an unknown key is
    still refused
    (test_a_relaxed_read_the_caller_sends_is_still_checked_and_the_provider_outranks_it,
    test_a_may_fill_read_the_caller_sends_is_still_checked).

    **On a** ``many`` **spec the Validator's parameters are each row's**, so
    the Validator's relaxings apply inside every row and none at the top
    level, where the list stays required and a read is relaxed only as a
    provider fills or may fill it (test_partial_leaves_the_list_and_the_reads_required,
    test_a_many_spec_s_read_its_kwargs_provider_fills_is_not_demanded_of_the_caller).
    The list's own refusal - absent, null, not a list - and the top level's
    are raised here; each row's is carried to ``validate_arguments`` as
    ``_CheckedRows``, to be reported with the Validator's.
    """
    owned, reached = server_filled(spec)
    # The schema relaxes ``partial`` through the same function, so the two
    # cannot disagree about which fields a partial call may leave out.
    parameters = relax_partial(spec, parameters)
    # One arc to coverage, each conjunct held by bind_arguments' tests:
    # test_a_selector_spec_returns_its_checked_arguments (the first: a selector
    # spec has no ``validator``) and
    # test_a_service_spec_with_no_validator_checks_its_target_reads_and_returns_nothing.
    if isinstance(spec, ServiceSpec) and spec.validator is not None:
        fields, fields_reached = reach(spec.input_data, spec.validator.parameters())
        if spec.many:
            return _check_bulk(
                _relaxed(parameters, reached),
                arguments,
                name=spec.many_argument,
                unknown_arguments=unknown_arguments,
                owned=owned,
                owned_in_rows=fields,
                reached_in_rows=fields_reached,
            )
        owned |= fields
        reached |= fields_reached
    return _without(
        check_arguments(
            _relaxed(parameters, reached), arguments, unknown_arguments=unknown_arguments
        ),
        owned,
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


def server_filled(spec: ServiceSpec | SelectorSpec) -> tuple[frozenset[str], frozenset[str]]:
    """The reads a ``kwargs`` provider fills where its values reach them, and the reads it fills or may fill.

    **A provider relaxes only the parameters its values reach**, so a key it
    fills or may fill is relaxed where the callable reading it is called
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
    than as that union, so the relaxing never outruns the delivery
    (test_a_target_read_is_relaxed_only_by_the_lookup_s_own_provider).

    The first set is the ``filled`` keys alone, whose caller's value is
    dropped (see ``_without``). The second adds a ``declinable`` key, and
    every parameter in the seat of a provider whose return says nothing about
    its keys, since it may fill any of them
    (test_a_may_fill_read_the_provider_answers_reaches_the_service): those
    are relaxed and kept as the caller's
    (test_a_declinable_key_stays_the_caller_s).
    """
    owned: frozenset[str] = frozenset()
    reached: frozenset[str] = frozenset()
    for provider, reads in read_seats(spec):
        filled, may_fill = reach(provider, reads)
        owned |= filled
        reached |= may_fill
    return owned, reached


def read_seats(
    spec: ServiceSpec | SelectorSpec,
) -> list[tuple[Callable[..., Any] | None, Parameters]]:
    """Each selector or service seat of ``spec``: the ``kwargs`` provider, and the reads its values reach."""
    if isinstance(spec, SelectorSpec):
        return [(spec.kwargs, spec.reads)]
    seats: list[tuple[Callable[..., Any] | None, Parameters]] = [(spec.kwargs, spec.reads)]
    target = spec.target_selector_spec()
    if target is not None:
        seats.append((target.kwargs, target.reads))
    return seats


def reach(
    provider: Callable[..., Any] | None, parameters: Parameters
) -> tuple[frozenset[str], frozenset[str]]:
    """The names in ``parameters`` that ``provider`` is annotated to fill, and those it fills or may fill.

    A typed provider may fill its ``filled`` and its ``declinable`` keys. One
    whose return says nothing about its keys may fill every name its values
    reach, and is annotated to fill none. No provider fills nothing.
    """
    keys = provider_keys(provider)
    names = parameters.names()
    if keys is None:
        return frozenset(), names
    return names & keys.filled, names & (keys.filled | keys.declinable)


def _owned(provider: Callable[..., Any] | None) -> frozenset[str]:
    """The keys ``provider`` is annotated to fill and may not decline; none if it does not say."""
    keys = provider_keys(provider)
    return keys.filled if keys is not None else frozenset()


def _check_bulk(
    parameters: Parameters,
    arguments: Mapping[str, Any],
    *,
    name: str,
    unknown_arguments: UnknownArguments,
    owned: frozenset[str],
    owned_in_rows: frozenset[str],
    reached_in_rows: frozenset[str],
) -> dict[str, Any]:
    """The top level of a ``many`` call checked here, and each row checked on its own.

    Each row is the list's own ``items``, as ``relax_partial`` left them,
    with what ``input_data`` fills or may fill relaxed on top
    (test_a_many_row_field_an_untyped_input_data_may_fill_is_relaxed_in_each_row).
    ``owned`` is what a typed ``kwargs`` provider fills at the top level and
    ``owned_in_rows`` what ``input_data`` fills in each row: dropped from
    each once checked (see ``_without``).

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
    rows = _relaxed(cast(Parameters, the_list.items), reached_in_rows)
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


def _relaxed(parameters: Parameters, reached: frozenset[str]) -> Parameters:
    """``parameters`` with the ones a provider fills or may fill optional, at the top level only.

    A copy, made for the shape check alone, so the declaration every other
    reader sees - the schema, ``required`` - is untouched. Only the top
    level, because a provider fills a whole argument, never a field inside one.
    """
    return Parameters.of(
        *(
            replace(param, required=False) if param.name in reached else param
            for param in parameters
        )
    )


def _refuse_absent(parameters: Parameters, pool: Mapping[str, Any]) -> None:
    """Refuse every parameter in ``parameters`` that is required of the call and absent from ``pool``.

    The seat's half of a parameter a provider fills or may fill, which the
    shape check does not demand: once the provider has answered, the
    declaration's ``required`` is checked against the pool the callable is
    called from, for every parameter the seat takes, whoever filled it.
    ``check_arguments`` itself answers, over the absent ones with no
    arguments, so the refusal is the shape check's own, in its wording and
    code and keyed by the parameter, and requires what it requires: a
    parameter ``required`` and declaring no default. Its conjuncts are held
    at the seat by test_an_optional_read_nobody_fills_is_not_refused_at_the_seat
    and test_a_required_read_declaring_a_default_is_not_refused_at_the_seat.
    So a read declared required that a provider declines is refused though
    the callable has a default of its own, or takes ``**`` whatever arrives
    (test_a_required_read_the_provider_declines_is_refused_though_its_callable_has_a_default).
    ``call_keywords`` stays the backstop for a callable parameter with no
    default that no declaration requires.
    """
    check_arguments(Parameters.of(*(param for param in parameters if param.name not in pool)), {})


def selector_pool(
    selector_spec: SelectorSpec,
    checked: Mapping[str, Any],
    *,
    principal: Any,
    pool_seeds: PoolSeeds,
    keywords: CheckKeywords,
    shapes: Mapping[str, Any],
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
    it absent. A ``reflected`` read a registered seed fills is no argument of
    the call, so the seed's value is the one here
    (test_a_caller_s_value_for_a_reflected_read_never_reaches_its_callable).

    **Then the seat's presence check**: every read the selector declares
    required with no default must be in the assembled pool, whoever filled
    it, or the call is refused as ``InvalidArguments`` keyed by the read (see
    ``_refuse_absent``). It is where a read a provider fills or may fill,
    which the shape check let through absent, is refused when nobody filled
    it (test_a_selector_spec_s_read_an_untyped_provider_may_fill,
    test_a_target_read_an_untyped_lookup_provider_may_fill), after
    class-level authorization and before the selector runs.

    ``progress`` is passed only for a selector spec's own selector, which is
    that spec's run (see ``call_pool``), and is the pool's ``progress``, as
    it is a service's. The spec's ``progress_reporter`` is not joined here:
    only the run hears it, joined to its keywords by ``with_run_progress``
    once they are bound, as a service's run is. A nested selector declaring
    one is refused when the service spec is built.

    ``extra_kwargs`` is the call's overlay, merged beneath the ``kwargs``
    provider's answer (see ``overlaid``); only a selector spec's own selector
    is handed one, never a service spec's target selector.

    ``keywords`` is what the call's checks were offered: its context, added
    beside the seeds once they are resolved, as every pool dispatch builds
    carries it, and the seeds a check named, taken as they are
    (``seeded_base``).

    ``shapes`` is the seed of that name: what the caller sent for the shapes
    of the spec being dispatched, read off ``shapes_sent``. Passed rather than
    read off ``selector_spec``, because a service spec's target selector
    declares no shapes of its own and is handed none of the write's, on any
    route (test_a_target_selector_is_handed_no_shapes_on_any_route).
    """
    reads = selector_spec.reads.names()
    base = seeded_base(
        principal,
        progress=progress,
        pool_seeds=pool_seeds,
        early=keywords.seeds,
        call_context=keywords.call_context,
    )
    pool = {
        **base,
        CALL_CONTEXT: keywords.call_context,
        SHAPES: shapes,
        **{name: value for name, value in checked.items() if name in reads},
    }
    pool.update(
        overlaid(
            extra_kwargs,
            provide(
                selector_spec.kwargs,
                pool,
                label="SelectorSpec.kwargs",
                reserved=pool_seeds.reserved | CALL_SEEDS,
            ),
            selector_spec.kwargs,
            label="extra_kwargs",
            reserved=pool_seeds.reserved | CALL_SEEDS,
        )
    )
    _refuse_absent(selector_spec.reads, pool)
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
    ``base_pool``'s, the call's context and its ``shapes``, since no read and
    no provided key may take one
    (test_a_selector_spec_s_progress_provider_is_called_from_the_base_pool,
    and test_a_selector_spec_s_callables_receive_the_shapes_the_presenter_is_handed
    for the reporter that names ``shapes``),
    as a service's provider is called from its base pool and the context
    (test_a_progress_provider_is_handed_the_call_context_on_either_kind_of_spec).
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
    _refuse_seeded(provided, label=label, reserved=reserved)
    return provided


def _refuse_seeded(provided: Mapping[str, Any], *, label: str, reserved: frozenset[str]) -> None:
    """Refuse a provider's key that names a seed: ``provide``'s rule, and the overlay's."""
    taken = sorted(provided.keys() & reserved)
    if taken:
        raise ImproperlyConfigured(
            f"{label} returned the key(s) {taken}, which dispatch seeds itself. A "
            "provider's value must never outrank a seeded one; rename the key."
        )


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
            asked=f"The precondition {callable_name(precondition)}",
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


def call_pool(
    principal: Any,
    pool_seeds: PoolSeeds,
    entries: Mapping[str, Any],
    *,
    early: Mapping[str, Any],
    call_context: Mapping[str, Any],
    progress: ProgressReporter | None = None,
) -> dict[str, Any]:
    """The base pool, then this call's own entries on top of it: the output selector's pool.

    ``early`` is the seeds a check of the call named, taken as they are
    (``seeded_base``).

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
    seed occupies but a ``reflected`` read, which it seated so no argument
    carries it, and a top-level Validator field, which ``prepare_service``
    keeps out of the spread; ``prepare_service`` refused every other
    validated, bound or provided key,
    ``provide`` a selector's provided one, and the entries dispatch adds
    itself (``data``, ``instance``, ``collection``, ``result``, and
    ``call_context`` and ``shapes``, the call's context and its shape values,
    which every pool dispatch builds carries) are names no project can
    register.
    """
    pool = seeded_base(
        principal, progress=progress, pool_seeds=pool_seeds, early=early, call_context=call_context
    )
    pool.update(entries)
    return pool


def reraise_unless_retrieve(
    selector_spec: SelectorSpec, error: ObjectDoesNotExist | Http404
) -> None:
    """Called from an ``except (ObjectDoesNotExist, Http404)``: what it means for this selector.

    A RETRIEVE selector written with ``.get()`` says "no such row" by raising,
    and that is the same missing row a ``.filter()`` returning nothing is, so
    it becomes ``None`` and the caller decides between not-found and
    ``allow_none``. ``Http404``, which ``get_object_or_404`` raises, is the
    same missing row said the way a view says it, and becomes ``None`` too.

    A LIST has no missing row, so either passes through untouched, and what
    it means there is the caller's: a ``DoesNotExist`` escaping a LIST is a
    fault inside the selector, while an ``Http404`` is the selector saying
    "not found", usually of a parent it looked up first, and the selector
    spec's own run and a write's collection selector answer it as
    ``NOT_FOUND`` (an output selector runs after the write, and never does).

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
    except (ObjectDoesNotExist, Http404) as error:
        # Each member and conjunct is held by its own test. Three are cases of
        # test_a_retrieve_s_missing_row_is_not_found_or_none_under_allow_none:
        # ``does-not-exist`` (``ObjectDoesNotExist``), ``http404`` (``Http404``)
        # and ``http404-allow-none`` (the kind). The others are
        # test_a_list_raising_does_not_exist_is_a_fault_and_passes_through (the
        # ``isinstance``) and test_a_list_output_selector_raising_http404_is_a_fault_after_the_run
        # (``after_the_run``: the write has run, so it is never reported not found).
        if isinstance(error, Http404) and selector_spec.kind is SelectorKind.LIST:
            if after_the_run:
                # Re-raised as a plain fault, because a bare ``Http404`` is
                # answered 404 by Django's handler and DRF's alike, which
                # would tell the caller a write that happened did not
                # (test_a_list_output_selector_raising_http404_is_a_fault_after_the_run).
                raise RuntimeError(
                    "The output selector raised Http404 after the service ran: a list "
                    "re-read has no missing row to report, and the write has happened."
                ) from error
            raise ListNotFound from error
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
    keywords: CheckKeywords,
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
    declares ``arguments`` as step two handed them, and ``keywords`` what step
    two offered. The context also carries the call's context and the
    ``shapes`` the caller sent, which ``pool`` holds under reserved names and
    ``ambient`` leaves out, since each has a field of its own. The field is the
    pool's own mapping, so the presenter reads the object the selector was
    handed.
    """
    grant = replace(grant, target_checked=False)
    handed = checks_arguments(checked)
    fillable = spec.reads.names()
    # Three conjuncts: test_a_retrieve_s_context_holds_the_seeds_and_never_its_reads_provider_or_overlay
    # fails without the first, test_ambient_holds_the_seeds_and_never_the_call_context
    # without the second, and test_ambient_never_holds_the_shapes without the third.
    context = PresentationContext(
        principal,
        ambient=MappingProxyType(
            {
                name: entry
                for name, entry in pool.items()
                if name in reserved and name != CALL_CONTEXT and name != SHAPES
            }
        ),
        call_context=keywords.call_context,
        shapes=pool[SHAPES],
    )
    if spec.kind is SelectorKind.LIST:
        authorize_scope(spec, principal, value, grant=grant, arguments=handed, **keywords.offered())
        run_preconditions(spec, {**pool, "collection": value}, fillable=fillable)
        return DispatchResult(kind="list", value=value, context=context)
    if value is not None:
        authorize_target(
            spec, principal, value, grant=grant, arguments=handed, **keywords.offered()
        )
        run_preconditions(spec, {**pool, "instance": value}, fillable=fillable)
    elif not spec.allow_none:
        return NOT_FOUND
    return DispatchResult(kind="instance", value=value, context=context)


def target_entry(spec: ServiceSpec, target: Any) -> dict[str, Any]:
    """``target`` under the pool name a service spec hands it to its service as.

    ``instance`` for a spec with an instance selector, ``None`` included,
    ``collection`` for one with a collection selector, and nothing for a
    create. The one rule ``walk_target`` returns its entry by and
    ``bind_arguments`` fills a ``ValidationContext``'s ``resolved`` by, so a
    Validator's callable names the target as the service will.
    """
    if spec.instance_selector_spec is not None:
        return {"instance": target}
    if spec.collection_selector_spec is not None:
        return {"collection": target}
    return {}


def walk_target(
    spec: ServiceSpec,
    principal: Any,
    checked: Mapping[str, Any],
    *,
    grant: Grant,
    pool_seeds: PoolSeeds,
    keywords: CheckKeywords,
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
    - **A collection**, empty or not: ``authorize_scope`` of the set. A
      collection selector raising ``Http404`` is ``NOT_FOUND``, with no scope
      check, since there is no set to ask it of
      (test_a_write_whose_collection_selector_raises_http404_is_not_found).
    - **A create**, which resolves nothing: ``authorize_scope`` of ``None``.

    Each is handed ``checked`` for a check that declares ``arguments``, as
    step two was, and offered what step two was offered, ``keywords``; the
    target selector's pool carries its context.

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
    offered = keywords.offered()
    handed = checks_arguments(checked)
    # The target selector is handed no shapes, on any route. Under
    # ``resolve_target`` the arguments are narrowed to the target's own
    # parameters, so the write's shapes are not among them; handing them here
    # would let one selector see different values by route, and one that
    # filters by them write a different row than the page showed. So the lookup
    # reads the same empty mapping everywhere, at both pools below, each held
    # by its own case of test_a_target_selector_is_handed_no_shapes_on_any_route
    # (instance and collection; sync, async and ``resolve_target``).
    # A selector that declares ``shapes`` is not refused: it is often a read's
    # own selector reused, and an empty mapping lets that reuse keep running.
    no_shapes: Mapping[str, Any] = MappingProxyType({})
    instance_spec = spec.instance_selector_spec
    collection_spec = spec.collection_selector_spec
    # The target lookups get no live reporter, and nor does the output selector
    # in ``finish_service``: neither is the run (see ``call_pool``).
    if instance_spec is not None:
        if target is UNSET:
            pool = selector_pool(
                instance_spec,
                checked,
                principal=principal,
                pool_seeds=pool_seeds,
                keywords=keywords,
                shapes=no_shapes,
            )
            target = lookup(
                instance_spec, pool, source=INSTANCE_SOURCE, reserved=pool_seeds.reserved
            )
        if target is not None:
            authorize_target(spec, principal, target, grant=grant, arguments=handed, **offered)
        elif not instance_spec.allow_none:
            return NOT_FOUND
        else:
            authorize_scope(spec, principal, None, grant=grant, arguments=handed, **offered)
        return target_entry(spec, target)
    if collection_spec is not None:
        if target is UNSET:
            pool = selector_pool(
                collection_spec,
                checked,
                principal=principal,
                pool_seeds=pool_seeds,
                keywords=keywords,
                shapes=no_shapes,
            )
            try:
                target = lookup(
                    collection_spec, pool, source=COLLECTION_SOURCE, reserved=pool_seeds.reserved
                )
            except ListNotFound:
                # The collection selector's own "not found", of a parent it
                # looked up: there is no set to scope-check, so nothing is.
                # Only ListNotFound: an Http404 from shaping passes through
                # (test_a_collection_selector_s_extend_queryset_http404_passes_through,
                # in test_dispatch.py and test_resolve_target.py).
                return NOT_FOUND
        authorize_scope(spec, principal, target, grant=grant, arguments=handed, **offered)
        return target_entry(spec, target)
    # One arc to coverage, so each conjunct is held by its own test: a create
    # dispatched with no ``target=`` (test_a_create_asks_the_scope_check_of_nothing)
    # the first, test_a_create_takes_a_pre_resolved_none_and_refuses_a_row the second.
    if target is not UNSET and target is not None:
        raise TypeError(
            "dispatch() was handed a target= for a ServiceSpec that declares no target "
            "selector. A create acts on no existing row; pass target=None or nothing."
        )
    authorize_scope(spec, principal, None, grant=grant, arguments=handed, **offered)
    return target_entry(spec, None)


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
    call_context: dict[str, Any],
    provider_answered: bool,
    ambient: Mapping[str, Any] = MappingProxyType({}),
    resolved: Mapping[str, Any] = MappingProxyType({}),
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
    proxy over its top level, whose values are the call's own, or empty for
    ``bind_arguments`` handed no ``pool_seeds``.
    Its ``resolved`` is ``resolved``, the target under its pool name (see
    ``target_entry``), behind a read-only proxy of its own. Its
    ``call_context`` is ``call_context``, the call's own dict and never a
    copy. A spec
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
    context = ValidationContext(
        principal,
        target,
        partial=spec.partial,
        ambient=ambient,
        resolved=MappingProxyType(dict(resolved)),
        call_context=call_context,
    )
    # The presence check, before the Validator runs, once ``input_data`` has
    # answered: a field the shape check let through absent, because the
    # provider fills or may fill it, is held to its declaration against the
    # caller's arguments and the provider's answer merged, as
    # ``_refuse_absent`` holds a read. So a Validator that returns what it is
    # handed never runs without a required field, and every Validator kind is
    # refused in the shape check's words
    # (test_a_required_field_nobody_filled_is_refused_before_the_validator_runs).
    # Read through ``relax_partial``, so a partial call still leaves any field
    # out (test_a_partial_spec_s_field_nobody_filled_is_still_not_required).
    # Not made when no provider ran - ``bind_arguments`` - where an absent
    # field the provider would fill is the Validator's to refuse
    # (test_a_field_input_data_fills_is_left_to_the_validator_which_runs_no_provider).
    relaxed = relax_partial(spec, spec.parameters()) if provider_answered else Parameters.of()
    if spec.many:
        the_list = next((param for param in relaxed if param.name == spec.many_argument), None)
        return _validate_rows(
            validator,
            checked[spec.many_argument],
            spec.many_argument,
            context,
            server_input,
            row_parameters=Parameters.of()
            if the_list is None
            else cast(Parameters, the_list.items),
        )
    merged = {**checked, **server_input}
    _refuse_absent(Parameters.of(*(param for param in relaxed if param.name in declared)), merged)
    own = {name: value for name, value in merged.items() if name in declared}
    return validator.validated(own, context)


def _validate_rows(
    validator: Validator,
    checked: _CheckedRows,
    name: str,
    context: ValidationContext,
    server_input: Mapping[str, Any],
    *,
    row_parameters: Parameters,
) -> Validated:
    """``validated_many()`` on the rows the shape check passed, and one refusal for every failing row.

    Each row is first held to ``row_parameters``, the list's rows as
    ``relax_partial`` left them, with ``input_data`` merged over it: a row
    missing a required field nobody filled is refused under its index, as a
    row the shape check refused is, and never reaches the Validator
    (test_a_many_row_field_nobody_filled_is_refused_in_its_row).
    """
    declared = validator.parameters().names()
    errors = dict(checked.errors)
    rows: dict[int, dict[str, Any]] = {}
    for index, row in checked.rows.items():
        merged = {**row, **server_input}
        try:
            _refuse_absent(row_parameters, merged)
        except InvalidArguments as refused:
            errors[index] = refused.detail
            continue
        # Only the keys the Validator declares, as on a single call: a row's
        # own unknown key was refused by the shape check, so only a provider's
        # can reach here (test_each_row_s_validator_sees_only_the_keys_it_declares).
        rows[index] = {key: value for key, value in merged.items() if key in declared}
    checked = _CheckedRows(rows, errors)
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
    call_context: dict[str, Any],
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

    1. The base pool: ``user``, ``progress`` and every registered seed, and
       ``call_context``, the call's context.
    2. The validated ``values``, each by name.
    3. The spec's ``reads``, as the caller sent them.
    4. ``data``, the Validator's ``data``, and what else the Validator binds
       for the call (its ``Validated.pool``).
    5. The spec's ``kwargs`` provider, the author's values after the caller's,
       over the call's ``extra_kwargs`` overlay.
    6. ``instance`` or ``collection``.

    No entry outranks a seed. A parameter named after one is refused by
    ``open_call``, but for a ``reflected`` read, which is no argument of the
    call and so carries no value of its own, and a top-level Validator field
    named like a registered seed: its validated value reaches the service in
    ``data`` alone and is never spread into the pool by name, so the seed
    keeps its own value
    (test_a_field_named_like_a_registered_seed_validates_into_data_and_the_pool_keeps_the_seed,
    test_input_data_filling_a_seed_named_field_reaches_data_and_never_the_pool).
    A validated value the Validator returns under a seed's name *without
    declaring it* is refused here, as is a bound value or a provider key
    named after one, and a bound value named after a validated value or a
    parameter. A
    read and a Validator parameter of one name are refused when
    ``parameters()`` is assembled, so a read outranks only a value the
    Validator returns without declaring it, as djangorestframework-services'
    route captures outrank the spread body
    (test_a_read_outranks_a_validated_value_of_its_name). The two providers are called from the base pool, the
    ``reads`` and the resolved target, and never see the Validator's values:
    ``input_data`` runs before the Validator, and ``kwargs`` is read the same.

    **Once the pool is assembled, the seat's presence check**: every one of
    the spec's ``reads`` declared required with no default must be in it,
    whoever filled it, or the call is refused as ``InvalidArguments`` keyed by
    the read (see ``_refuse_absent``), before the affordances, the
    preconditions and the run's transaction. It is where a read the spec's
    ``kwargs`` provider fills or may fill, which the shape check let through
    absent, is refused when nobody filled it
    (test_a_may_fill_read_nobody_fills_is_refused_at_the_service_seat), so it
    answers after the target is resolved and checked and after the Validator.
    """
    keywords = CheckKeywords(call_context)
    checked, granted = open_call(
        spec,
        principal,
        arguments,
        grant=grant,
        pool_seeds=pool_seeds,
        unknown_arguments=unknown_arguments,
        overlay=overlay,
        keywords=keywords,
    )
    resolved = walk_target(
        spec,
        principal,
        checked,
        grant=granted,
        pool_seeds=pool_seeds,
        target=target,
        keywords=keywords,
    )
    if isinstance(resolved, DispatchResult):
        return resolved
    # The row, the set, or ``None`` for a create: what the Validator's context
    # and the run's result carry.
    target = next(iter(resolved.values()), None)
    reserved = pool_seeds.reserved
    # A provider's or the overlay's key may not name the call's ``request`` or
    # ``view`` either, or it would outrank the context's in the service's pool
    # (test_a_provider_returning_request_is_refused).
    provided = reserved | CALL_SEEDS
    # One base pool for the call, so a seed that queries resolves once for the
    # providers and the service alike. Its ``progress`` is the transport's: the
    # spec's own sink is the run's alone, and joins the run's keywords last.
    base = seeded_base(
        principal,
        progress=progress,
        pool_seeds=pool_seeds,
        early=keywords.seeds,
        call_context=call_context,
    )
    # Behind a proxy, so neither the Validator nor the presenter can change the
    # pool the service is called from. No copy: nothing writes to ``base`` once
    # it is built, and every pool made from it is a dict of its own.
    ambient = MappingProxyType(base)
    # The call's context beside the seeds rather than in ``base``, so
    # ``ambient`` stays the seeds alone and never the dict itself, which has a
    # field of its own on both
    # contexts (test_ambient_holds_the_seeds_and_never_the_call_context). The
    # shapes the same way, for the presenter's field of its own and for the
    # Validator, which never sees them (test_ambient_never_holds_the_shapes).
    shapes = shapes_sent(spec, checked)
    # The presenter's own mapping, not a copy: held by the identity assertion of
    # test_a_service_spec_s_callables_receive_the_shapes_the_presenter_is_handed.
    surroundings = {**base, CALL_CONTEXT: call_context, SHAPES: shapes}
    declared_reads = spec.reads.names()
    reads = {name: value for name, value in checked.items() if name in declared_reads}
    providers_pool = {**surroundings, **reads, **resolved}
    server_input = resolve_provider(spec.input_data, providers_pool, label="ServiceSpec.input_data")
    validated = validate_arguments(
        spec,
        checked,
        principal=principal,
        target=target,
        server_input=server_input,
        call_context=call_context,
        provider_answered=True,
        ambient=ambient,
        resolved=resolved,
    )
    values = validated.values
    # What the pool spreads by name: the values less a top-level field named
    # like a registered seed or the call's ``request`` or ``view``, which
    # reaches the service in ``data`` alone, so the service naming it reads the
    # seed or the context's (test_a_validator_field_named_request_takes_the_seat). A
    # new mapping, never ``values`` changed in place: the base ``validated()``
    # hands one dict as ``values`` and ``data``, so a pop would drop the field
    # from ``data`` too
    # (test_a_field_named_like_a_registered_seed_validates_into_data_and_the_pool_keeps_the_seed).
    fields = seed_named_fields(spec, pool_seeds.names | CALL_SEEDS)
    spread = {name: value for name, value in values.items() if name not in fields}
    # A Validator returning ``user`` is a bug, and letting its value outrank the
    # seed silently would be the worse one: the service would act as whoever
    # the arguments named. Refused rather than dropped, so the bug is found.
    # Read on what the pool spreads, so a seed-named value the Validator
    # returns without declaring it is still refused:
    # test_a_validated_value_named_after_a_seed_is_refused fails if every
    # seed's name is left out of the spread rather than the declared fields'.
    # The call's ``request`` and ``view`` too, or a returned value would
    # outrank the context's (test_a_validator_returning_either_is_refused).
    seeded = sorted(spread.keys() & provided)
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
    # test_a_bound_value_naming_a_parameter_is_refused (``a-read``, ``a-field-left-out``),
    # and the call's names by test_a_validator_binding_either_is_refused.
    named = provided | values.keys() | spec.parameters().names()
    bound = sorted(validated.pool.keys() & named)
    if bound:
        raise ImproperlyConfigured(
            f"The Validator bound the key(s) {bound}, which dispatch seeds, the Validator "
            "returned as a value, or the spec declares as a parameter. A value bound for "
            "the call needs a name of its own."
        )
    # The overlay is the lowest tier: beneath the spec's provider, and beneath
    # what the Validator computed or bound, whose keys it never replaces. Its
    # entry is dropped for the call rather than refused, since whether the
    # Validator computes a key can turn on what the caller sent
    # (test_the_overlay_fills_what_the_validator_left_uncomputed_on_this_call).
    # Each side of the union is held by a case of
    # test_a_value_the_validator_computed_outranks_the_overlay:
    # ``a-validated-value`` fails without the values, ``a-bound-value`` without
    # the pool. The values the pool spreads, so an overlay key named like a
    # seed-named field still reaches ``overlaid``, which refuses a seed's name
    # (test_an_overlay_key_named_like_the_seed_is_still_refused_beside_such_a_field).
    computed = spread.keys() | validated.pool.keys()
    author = overlaid(
        {name: value for name, value in overlay.kwargs.items() if name not in computed},
        provide(spec.kwargs, providers_pool, label="ServiceSpec.kwargs", reserved=provided),
        spec.kwargs,
        label="extra_kwargs",
        reserved=provided,
    )
    pool = {
        **surroundings,
        **spread,
        **reads,
        "data": validated.data,
        **validated.pool,
        **author,
        **resolved,
    }
    # The seat's presence check, once the provider has answered: after the
    # Validator and before the affordances, as a missing argument answers.
    _refuse_absent(spec.reads, pool)
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
    enforce_affordances(
        spec,
        pool,
        instance=resolved.get("instance"),
        reserved=reserved,
        call_context=call_context,
    )
    # Then the preconditions, still before the run and in the same hop: after
    # the affordances, djangorestframework-services' order
    # (test_an_affordance_answers_before_a_precondition).
    run_preconditions(spec, pool, fillable=fillable)
    # Last, once nothing can refuse the call: the run's reporter, with the
    # spec's own sink beside the transport's. Only for a service that takes
    # ``progress``, so one that never could report never calls the provider.
    if "progress" in kwargs:
        kwargs["progress"] = run_progress(
            spec.progress_reporter, spec.service, surroundings, transport=progress
        )
    return Prepared(
        principal,
        target,
        validated.data,
        kwargs,
        ambient,
        call_context,
        shapes,
        MappingProxyType(dict(keywords.seeds)),
    )


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
    # djangorestframework-services renders it, and a ``returns_many`` spec
    # declares its return a list of rows; an output selector's kind still
    # decides what its re-read is, and is refused beside ``returns_many``. A
    # ``None`` either returns stays one value, presented as ``None`` as any
    # service's is: as a list it would be refused by ``present`` after the
    # write had committed. One arc to coverage, so each operand is named:
    # test_the_service_runs_once_with_every_validated_row holds ``many``,
    # TestReturnsMany.test_a_list_of_rows_is_presented_row_by_row
    # ``returns_many``, and test_a_many_service_returning_none_presents_none
    # and TestReturnsMany.test_a_none_return_presents_none the ``None``.
    lists = spec.many or spec.returns_many
    kind: Literal["instance", "list"] = "list" if lists and result is not None else "instance"
    if output_spec is not None:
        # The service's return under both names djangorestframework-services
        # binds it by, so a re-read declares whichever its author wrote:
        # ``instance`` here is what the service returned, not the target it
        # resolved, and it is bound whatever the return is, ``None`` included.
        pool = call_pool(
            prepared.principal,
            pool_seeds,
            {
                "instance": result,
                "result": result,
                CALL_CONTEXT: prepared.call_context,
                # Not a copy, for the same test as ``surroundings`` above.
                SHAPES: prepared.shapes,
            },
            early=prepared.early_seeds,
            call_context=prepared.call_context,
        )
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
        context=PresentationContext(
            prepared.principal,
            prepared.target,
            prepared.ambient,
            call_context=prepared.call_context,
            shapes=prepared.shapes,
        ),
    )


def server_arguments_label(spec: ServiceSpec | SelectorSpec) -> str:
    """``spec`` as a ``ServerArguments`` refusal names it: its kind and its callable.

    For ``check_server_arguments`` and ``apply_server_arguments`` alike, so a
    transport binding many tools reads which one is misconfigured.
    """
    fn = spec.service if isinstance(spec, ServiceSpec) else spec.selector
    return f"{type(spec).__name__} for {callable_name(fn)}"


def checked_server_values(
    spec: ServiceSpec | SelectorSpec, parameters: Parameters, values: Mapping[str, Any]
) -> dict[str, Any]:
    """A binding's ``values``, each checked against its own parameter, as the shape check hands it on.

    One rule for ``check_server_arguments``, which runs it where a transport
    is built, and ``apply_server_arguments``, which runs it on each call, so
    the value a call receives is the one the construction-time check passed.
    Only the bound parameters are checked, so a bound value is never refused
    for a parameter the caller fills. A refusal is the server's mistake,
    raised as ``ImproperlyConfigured`` with the shape check's refusal as its
    cause, never as ``InvalidArguments``: no caller can correct a value it
    neither sent nor sees. A bound name no parameter declares is refused the
    same way, as the closed argument set refuses it.
    """
    own = Parameters.of(*(parameter for parameter in parameters if parameter.name in values))
    try:
        return check_arguments(own, values)
    except InvalidArguments as refused:
        raise ImproperlyConfigured(
            f"{server_arguments_label(spec)}: ServerArguments binds a value its parameter "
            f"refuses: {refused.detail}. A bound value is the server's, so no caller can "
            "correct it; bind the spelling the declaration takes, such as a UUID's or a "
            "date's string."
        ) from refused
