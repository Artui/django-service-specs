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

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal

from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist
from django.db.models import BooleanField, Value
from django.db.models.manager import BaseManager

from django_service_specs.affordances.enforce_affordances import enforce_affordances
from django_service_specs.affordances.utils import (
    affordance_expression,
    rows_with_affordances,
    split_affordances,
)
from django_service_specs.authorization.authorize import authorize
from django_service_specs.authorization.authorize_scope import authorize_scope
from django_service_specs.authorization.authorize_target import authorize_target
from django_service_specs.authorization.grant import Grant
from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.authorization.utils import is_deactivated
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.parameters.check_arguments import check_arguments
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.pool.base_pool import base_pool
from django_service_specs.pool.null_progress import null_progress
from django_service_specs.pool.pool_seeds import PoolSeeds
from django_service_specs.pool.provider_keys import provider_keys
from django_service_specs.pool.utils import deferred_progress, resolve_progress, resolve_provider
from django_service_specs.selectors.is_queryset import is_queryset
from django_service_specs.selectors.materialize_retrieve import materialize_retrieve
from django_service_specs.selectors.run_selector import run_selector
from django_service_specs.selectors.utils import apply_shaping, call_keywords
from django_service_specs.services.is_async import is_async
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.progress_reporter import ProgressReporter
from django_service_specs.types.unset import UNSET
from django_service_specs.validation.unknown_arguments import UnknownArguments
from django_service_specs.validation.validated import Validated
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator

NOT_FOUND = DispatchResult(kind="not_found")
"""A required row that does not exist. Frozen, so one instance serves every call."""

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


def open_call(
    spec: ServiceSpec | SelectorSpec,
    principal: Any,
    arguments: Mapping[str, Any],
    *,
    grant: Grant | None,
    pool_seeds: PoolSeeds,
    unknown_arguments: UnknownArguments,
    parameters: Parameters | None = None,
) -> tuple[dict[str, Any], Grant]:
    """Steps one and two: the checked arguments, and the grant the call runs under.

    ``parameters`` is what is checked, ``spec.parameters()`` unless given:
    ``resolve_target`` checks its target selector's alone.

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
    can see the collision.

    Class-level authorization runs before anything is resolved, so a principal
    it refuses learns nothing about which rows exist. It runs after the shape
    check, which reveals only what the declaration already says.
    """
    if is_deactivated(principal):
        raise PrincipalUnavailable()
    if parameters is None:
        parameters = spec.parameters()
    taken = sorted(parameters.names() & pool_seeds.reserved)
    if taken:
        raise ImproperlyConfigured(
            f"{type(spec).__name__} declares the parameter(s) {taken}, which a registered "
            "pool seed occupies. An argument must never meet a seed in one pool; rename "
            "the parameter."
        )
    checked = shape_check(spec, parameters, arguments, unknown_arguments=unknown_arguments)
    return checked, authorize(spec, principal, grant=grant)


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

    - **A parameter a typed provider fills, where that provider's values
      reach it** (see ``_server_filled``): not demanded of the caller, since
      the provider's values are merged over the caller's before the callable
      reading it is called; ``server_owned_keys`` tells a transport to hide
      exactly such a key. It is still required of the merged result: a
      provider that declines it after all, with ``UNSET`` or by leaving it
      out, leaves the usual refusal to the step that reads it - the
      Validator for one of its fields
      (test_a_filled_field_the_provider_declines_is_refused_by_the_validator),
      ``call_keywords`` for a read the service or a selector asks for
      (test_a_filled_read_the_provider_declines_is_refused_where_the_service_asks_for_it,
      test_a_target_read_the_lookup_s_provider_declines_is_refused_where_the_selector_asks).
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
    # One arc to coverage, each conjunct held by bind_arguments' tests:
    # test_a_selector_spec_returns_its_checked_arguments (the first: a selector
    # spec has no ``validator``) and
    # test_a_service_spec_with_no_validator_checks_its_target_reads_and_returns_nothing.
    if isinstance(spec, ServiceSpec) and spec.validator is not None:
        declared = spec.validator.parameters()
        fields = _filled(spec.input_data, declared)
        everywhere = declared.names() if spec.partial else frozenset()
        if spec.many:
            return _check_bulk(
                _relaxed(parameters, frozenset(), reads),
                _relaxed(declared, everywhere, fields),
                arguments,
                name=spec.many_argument,
                unknown_arguments=unknown_arguments,
            )
        parameters = _relaxed(parameters, everywhere, reads | fields)
    else:
        parameters = _relaxed(parameters, frozenset(), reads)
    return check_arguments(parameters, arguments, unknown_arguments=unknown_arguments)


def _server_filled(spec: ServiceSpec | SelectorSpec) -> frozenset[str]:
    """The reads a typed ``kwargs`` provider fills where its values reach them: no caller's to send.

    **A provider relaxes only the parameters its values reach**, so a key it
    is annotated to fill is relaxed where the callable reading it is called
    with the provider's value, and stays required everywhere else:

    - A selector's own ``kwargs`` is merged over its ``reads`` in
      ``selector_pool``, so it relaxes that selector's reads: a selector
      spec's
      (test_a_selector_spec_s_read_its_kwargs_provider_fills_is_not_demanded_of_the_caller),
      and a service spec's target selector's
      (test_a_target_read_the_lookup_s_kwargs_provider_fills_is_not_demanded_of_the_caller).
      It never reaches the service
      (test_a_read_the_lookup_s_kwargs_provider_fills_stays_required_of_the_service).
    - A service spec's ``kwargs`` is merged into the service's pool after
      the caller's ``reads``, so it relaxes the spec's ``reads``
      (test_a_read_the_spec_s_kwargs_provider_fills_is_not_demanded_of_the_caller).
      It is called once the target is resolved, and after the Validator ran,
      so a target selector's read and a Validator field it names stay
      required (test_a_target_read_the_spec_s_kwargs_provider_fills_stays_required,
      test_a_validator_field_the_spec_s_kwargs_provider_fills_stays_required).
    - ``input_data`` is merged into the Validator's arguments alone, so it
      relaxes the Validator's fields - in ``shape_check``, at the top level or
      in each row of a ``many`` spec - and never a read
      (test_a_filled_key_naming_a_read_stays_required).

    Only ``filled`` keys: a ``declinable`` one stays the caller's. And a
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
    rows: Parameters,
    arguments: Mapping[str, Any],
    *,
    name: str,
    unknown_arguments: UnknownArguments,
) -> dict[str, Any]:
    """The top level of a ``many`` call checked here, and each row checked on its own.

    A list is checked at the top level as an empty one, so the list itself
    and every argument beside it are checked as declared while no row is: a
    row checked there would raise with the others, before the Validator could
    add its own refusals of the rest. Anything that is not a list is checked
    as it was sent, and refused.
    """
    value = arguments.get(name) if isinstance(arguments, Mapping) else None
    if not isinstance(value, (list, tuple)):
        return check_arguments(parameters, arguments, unknown_arguments=unknown_arguments)
    checked = check_arguments(
        parameters, {**arguments, name: []}, unknown_arguments=unknown_arguments
    )
    cleaned: dict[int, dict[str, Any]] = {}
    errors: dict[int, Any] = {}
    for index, row in enumerate(value):
        # Each row as a top-level call, which is how the shape check reads a
        # row nested in a declared array too: the same unknown-key policy, and
        # a row that is no object refused under ``non_field_errors``.
        try:
            cleaned[index] = check_arguments(rows, row, unknown_arguments=unknown_arguments)
        except InvalidArguments as refused:
            errors[index] = refused.detail
    checked[name] = _CheckedRows(cleaned, errors)
    return checked


def _relaxed(parameters: Parameters, everywhere: frozenset[str], top: frozenset[str]) -> Parameters:
    """``parameters`` with the named ones optional: ``everywhere`` at every depth, ``top`` at the top.

    A copy, made for the shape check alone, so the declaration every other
    reader sees - the schema, ``required`` - is untouched.
    """
    # One arc to coverage, so each conjunct is held by its own test:
    # test_a_partial_spec_dispatched_with_one_field_reaches_the_service_with_that_field_alone
    # the first, and
    # test_an_input_data_provider_fills_a_required_validator_field_the_caller_left_out
    # the second.
    if not everywhere and not top:
        return parameters
    return Parameters.of(
        *(
            _optional(param)
            if param.name in everywhere
            else replace(param, required=False)
            if param.name in top
            else param
            for param in parameters
        )
    )


def _optional(param: Parameter) -> Parameter:
    """``param`` and everything declared below it made optional, as a partial serializer reads it."""
    items = param.items
    return replace(
        param,
        required=False,
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
) -> dict[str, Any]:
    """The pool a selector is called from: the base pool, its ``reads``, then its ``kwargs``.

    Only its own reads. A service spec's checked arguments also carry its
    Validator's, which have not been validated yet and are not the selector's
    to see. The spec's ``kwargs`` provider is called from the base pool and
    those reads, and what it returns is merged after them, so a key it answers
    is the author's whatever the caller sent: on a target selector it scopes
    the lookup (test_a_target_selector_s_kwargs_provider_scopes_the_lookup).

    ``progress`` is passed only for a selector spec's own selector, which is
    that spec's run (see ``call_pool``), and only that run hears the spec's
    ``progress_reporter``: a nested selector declaring one is refused when the
    service spec is built.
    """
    reads = selector_spec.reads.names()
    base = base_pool(user=principal, progress=progress, seeds=pool_seeds)
    pool = {**base, **{name: value for name, value in checked.items() if name in reads}}
    pool.update(
        provide(
            selector_spec.kwargs, pool, label="SelectorSpec.kwargs", reserved=pool_seeds.reserved
        )
    )
    pool["progress"] = run_progress(
        selector_spec.progress_reporter, selector_spec.selector, base, transport=progress
    )
    return pool


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
    check that can refuse the call has passed
    (test_an_async_service_s_progress_provider_is_resolved_before_the_run).
    With neither, ``null_progress``, as ``base_pool`` seeds it.
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
    """
    for precondition in spec.preconditions or ():
        precondition(**call_keywords(precondition, pool, fillable=fillable))


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
    """
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
    """
    fn = selector_spec.selector
    fillable: frozenset[str] = frozenset() if after_the_run else selector_spec.reads.names()
    kwargs = call_keywords(fn, pool, fillable=fillable)
    try:
        raw = run_selector(fn, kwargs)
    except ObjectDoesNotExist as error:
        reraise_unless_retrieve(selector_spec, error)
        return None
    return settle(selector_spec, raw, pool, source=source, reserved=reserved, fillable=fillable)


def conclude_selector(
    spec: SelectorSpec, value: Any, *, principal: Any, grant: Grant, pool: Mapping[str, Any]
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
    never told what a rule over it says. Never without a row, missing or
    ``None`` under ``allow_none``
    (test_a_selector_spec_s_preconditions_never_run_without_a_row).
    """
    fillable = spec.reads.names()
    if spec.kind is SelectorKind.LIST:
        authorize_scope(spec, principal, value, grant=grant)
        run_preconditions(spec, {**pool, "collection": value}, fillable=fillable)
        return DispatchResult(kind="list", value=value)
    if value is not None:
        authorize_target(spec, principal, value, grant=grant)
        run_preconditions(spec, {**pool, "instance": value}, fillable=fillable)
    elif not spec.allow_none:
        return NOT_FOUND
    return DispatchResult(kind="instance", value=value)


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

    ``target``, when given, is the target a caller resolved itself, and stands
    in for the lookup alone: the checks above still run on it, unless
    ``grant.target_checked`` says they ran already. A create takes ``None``
    there and nothing else, since it has no target to stand in for.
    """
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
            authorize_target(spec, principal, target, grant=grant)
        elif not instance_spec.allow_none:
            return NOT_FOUND
        else:
            authorize_scope(spec, principal, None, grant=grant)
        return {"instance": target}
    if collection_spec is not None:
        if target is UNSET:
            pool = selector_pool(
                collection_spec, checked, principal=principal, pool_seeds=pool_seeds
            )
            target = lookup(
                collection_spec, pool, source=COLLECTION_SOURCE, reserved=pool_seeds.reserved
            )
        authorize_scope(spec, principal, target, grant=grant)
        return {"collection": target}
    # One arc to coverage, so each conjunct is held by its own test: a create
    # dispatched with no ``target=`` (test_a_create_asks_the_scope_check_of_nothing)
    # the first, test_a_create_takes_a_pre_resolved_none_and_refuses_a_row the second.
    if target is not UNSET and target is not None:
        raise TypeError(
            "dispatch() was handed a target= for a ServiceSpec that declares no target "
            "selector. A create acts on no existing row; pass target=None or nothing."
        )
    authorize_scope(spec, principal, None, grant=grant)
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
) -> Validated:
    """Step five: the Validator's whole result, on only the arguments its own ``parameters()`` declare.

    Never the target selector's ``reads`` nor the spec's, which are not the
    Validator's to see (test_a_reads_argument_reaches_the_service_and_never_the_validator).
    ``server_input`` is the spec's ``input_data``, merged over the caller's
    arguments so its values are the author's; a key the Validator does not
    declare is not handed to it, as a serializer ignores a key it has no field
    for. The caller's arguments have been through the shape check, and the
    server's are the author's own values, which the Validator checks.

    ``ValidationContext.partial`` is the spec's ``partial``. A spec with no
    Validator validates nothing: its ``data`` is ``{}``, and every argument it
    takes is a read.

    **A** ``many`` **spec's Validator is run once per row**, on every row the
    shape check let through, each with ``server_input`` merged over it. A row
    it refuses is re-rooted under the row's index, beside the shape check's
    refusals, and the whole tree is raised as one ``InvalidArguments`` under
    ``many_argument`` once every row has been seen. Otherwise ``data`` is the
    list of each row's ``data`` and ``values`` holds the list of each row's
    values under ``many_argument``: neither is spread by field.
    """
    validator = spec.validator
    if validator is None:
        return Validated(values={}, data={})
    declared = validator.parameters().names()
    if spec.many:
        context = ValidationContext(principal, target, partial=spec.partial)
        return _validate_rows(
            validator, checked[spec.many_argument], spec.many_argument, context, server_input
        )
    merged = {**checked, **server_input}
    own = {name: value for name, value in merged.items() if name in declared}
    return validator.validated(own, ValidationContext(principal, target, partial=spec.partial))


def _validate_rows(
    validator: Validator,
    checked: _CheckedRows,
    name: str,
    context: ValidationContext,
    server_input: Mapping[str, Any],
) -> Validated:
    """``validated()`` on each row the shape check passed, and one refusal for every failing row."""
    declared = validator.parameters().names()
    errors = dict(checked.errors)
    values: list[dict[str, Any]] = []
    data: list[Any] = []
    for index, row in checked.rows.items():
        merged = {**row, **server_input}
        own = {key: value for key, value in merged.items() if key in declared}
        try:
            validated = validator.validated(own, context)
        except InvalidArguments as refused:
            errors[index] = refused.detail
            continue
        # A value bound for the call has no seat on a call of many rows: each
        # row would bind its own, and the service is called once. Refused
        # rather than dropped, as a bound value with no name of its own is.
        if validated.pool:
            raise ImproperlyConfigured(
                f"The Validator bound the key(s) {sorted(validated.pool)} for row {index} of a "
                "many call. A many spec's service is called once for every row, so a value "
                "bound for one row has nowhere to go; bind nothing on a many spec."
            )
        values.append(validated.values)
        data.append(validated.data)
    if errors:
        raise InvalidArguments({name: dict(sorted(errors.items()))})
    return Validated(values={name: values}, data=data)


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
    5. The spec's ``kwargs`` provider, the author's values after the caller's.
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
    declared_reads = spec.reads.names()
    reads = {name: value for name, value in checked.items() if name in declared_reads}
    providers_pool = {**base, **reads, **resolved}
    server_input = resolve_provider(spec.input_data, providers_pool, label="ServiceSpec.input_data")
    validated = validate_arguments(
        spec, checked, principal=principal, target=target, server_input=server_input
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
    # (``a-seed``, ``a-validated-value``) and
    # test_a_bound_value_naming_a_parameter_is_refused (``a-read``, ``a-field-left-out``).
    named = reserved | values.keys() | spec.parameters().names()
    bound = sorted(validated.pool.keys() & named)
    if bound:
        raise ImproperlyConfigured(
            f"The Validator bound the key(s) {bound}, which dispatch seeds, the Validator "
            "returned as a value, or the spec declares as a parameter. A value bound for "
            "the call needs a name of its own."
        )
    author = provide(spec.kwargs, providers_pool, label="ServiceSpec.kwargs", reserved=reserved)
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
    return Prepared(principal, target, validated.data, kwargs)


def finish_service(
    spec: ServiceSpec, prepared: Prepared, result: Any, *, pool_seeds: PoolSeeds
) -> DispatchResult:
    """The output selector, if declared, and the service spec's result.

    The output selector's pool is the base pool plus ``result``, the service's
    return; the arguments are not in it, because it re-reads what the service
    produced rather than what the caller asked for.

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
        pool = call_pool(prepared.principal, pool_seeds, {"result": result})
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
    )
