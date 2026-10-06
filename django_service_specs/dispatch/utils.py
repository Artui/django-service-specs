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

from collections.abc import Mapping
from dataclasses import dataclass
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
from django_service_specs.authorization.authorize_target import authorize_target
from django_service_specs.authorization.grant import Grant
from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.authorization.utils import is_deactivated
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.parameters.check_arguments import check_arguments
from django_service_specs.pool.base_pool import base_pool
from django_service_specs.pool.pool_seeds import PoolSeeds
from django_service_specs.selectors.utils import (
    apply_shaping,
    call_keywords,
    call_selector,
    is_queryset,
    materialize_retrieve,
)
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.progress_reporter import ProgressReporter
from django_service_specs.validation.unknown_arguments import UnknownArguments
from django_service_specs.validation.validation_context import ValidationContext

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
    data: dict[str, Any]
    kwargs: dict[str, Any]


def open_call(
    spec: ServiceSpec | SelectorSpec,
    principal: Any,
    arguments: Mapping[str, Any],
    *,
    grant: Grant | None,
    pool_seeds: PoolSeeds,
    unknown_arguments: UnknownArguments,
) -> tuple[dict[str, Any], Grant]:
    """Steps one and two: the checked arguments, and the grant the call runs under.

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
    parameters = spec.parameters()
    taken = sorted(parameters.names() & pool_seeds.reserved)
    if taken:
        raise ImproperlyConfigured(
            f"{type(spec).__name__} declares the parameter(s) {taken}, which a registered "
            "pool seed occupies. An argument must never meet a seed in one pool; rename "
            "the parameter."
        )
    checked = check_arguments(parameters, arguments, unknown_arguments=unknown_arguments)
    return checked, authorize(spec, principal, grant=grant)


def selector_pool(
    selector_spec: SelectorSpec,
    checked: Mapping[str, Any],
    *,
    principal: Any,
    pool_seeds: PoolSeeds,
    progress: ProgressReporter | None = None,
) -> dict[str, Any]:
    """The pool a selector is called from: the base pool, plus the arguments its ``reads`` declare.

    Only its own reads. A service spec's checked arguments also carry its
    Validator's, which have not been validated yet and are not the selector's
    to see. ``progress`` is passed only for a selector spec's own selector,
    which is that spec's run; see ``call_pool``.
    """
    reads = selector_spec.reads.names()
    return call_pool(
        principal,
        pool_seeds,
        {name: value for name, value in checked.items() if name in reads},
        progress=progress,
    )


def call_pool(
    principal: Any,
    pool_seeds: PoolSeeds,
    entries: Mapping[str, Any],
    *,
    progress: ProgressReporter | None = None,
) -> dict[str, Any]:
    """The base pool, then this call's own entries on top of it.

    ``progress`` is the caller's reporter, and is passed only for a pool a run
    is called from: a service's, or a selector spec's own selector's. A target
    or output selector's pool gets ``base_pool``'s no-op instead, deliberately,
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
    seed occupies, ``prepare_service`` every validated key, and the entries
    dispatch adds itself (``data``, ``instance``, ``collection``, ``result``)
    are names no project can register.
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

    An ``async def`` selector is bridged by ``call_selector``, driven from this
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
        raw = call_selector(fn, kwargs)
    except ObjectDoesNotExist as error:
        reraise_unless_retrieve(selector_spec, error)
        return None
    return settle(selector_spec, raw, pool, source=source, reserved=reserved, fillable=fillable)


def conclude_selector(
    spec: SelectorSpec, value: Any, *, principal: Any, grant: Grant
) -> DispatchResult:
    """Step four for a selector spec, and its result.

    The object-level check runs on a retrieved row and never on a list: a
    collection has no single object to check against. Nor on a ``None`` that
    ``allow_none`` let through, which is not a row anyone could be refused.
    """
    if spec.kind is SelectorKind.LIST:
        return DispatchResult(kind="list", value=value)
    if value is not None:
        authorize_target(spec, principal, value, grant=grant)
    elif not spec.allow_none:
        return NOT_FOUND
    return DispatchResult(kind="instance", value=value)


def validate_arguments(
    spec: ServiceSpec, checked: Mapping[str, Any], *, principal: Any, target: Any
) -> dict[str, Any]:
    """Step five: the Validator, on only the arguments its own ``parameters()`` declare.

    Never the target selector's ``reads``, which were the selector's to consume
    and are not the service's input. A spec with no Validator returns ``{}``:
    every argument it takes is its target selector's, and none reaches the
    service. The shape check has already run, so a Validator is only ever
    handed well-shaped arguments.
    """
    validator = spec.validator
    if validator is None:
        return {}
    declared = validator.parameters().names()
    own = {name: value for name, value in checked.items() if name in declared}
    return validator.validate(own, ValidationContext(principal, target))


def prepare_service(
    spec: ServiceSpec,
    principal: Any,
    arguments: Mapping[str, Any],
    *,
    grant: Grant | None,
    pool_seeds: PoolSeeds,
    unknown_arguments: UnknownArguments,
    progress: ProgressReporter | None,
) -> Prepared | DispatchResult:
    """Steps one to six for a service spec, and the keywords its run is called with.

    Returns ``NOT_FOUND`` when the instance selector resolves nothing and
    ``allow_none`` is off: the service never runs, and neither the Validator
    nor an affordance is asked. The pool carries ``instance`` when the spec
    declares an instance selector - the row, or ``None`` under ``allow_none``,
    so an upsert's service can declare it without a default - and
    ``collection`` when it declares a collection selector. A create carries
    neither.
    """
    checked, granted = open_call(
        spec,
        principal,
        arguments,
        grant=grant,
        pool_seeds=pool_seeds,
        unknown_arguments=unknown_arguments,
    )
    target: Any = None
    resolved: dict[str, Any] = {}
    instance_spec = spec.instance_selector_spec
    collection_spec = spec.collection_selector_spec
    # The target lookups get no live reporter, and nor does the output selector
    # in ``finish_service``: neither is the run (see ``call_pool``).
    if instance_spec is not None:
        pool = selector_pool(instance_spec, checked, principal=principal, pool_seeds=pool_seeds)
        target = lookup(instance_spec, pool, source=INSTANCE_SOURCE, reserved=pool_seeds.reserved)
        if target is not None:
            authorize_target(spec, principal, target, grant=granted)
        elif not instance_spec.allow_none:
            return NOT_FOUND
        resolved["instance"] = target
    elif collection_spec is not None:
        pool = selector_pool(collection_spec, checked, principal=principal, pool_seeds=pool_seeds)
        target = lookup(
            collection_spec, pool, source=COLLECTION_SOURCE, reserved=pool_seeds.reserved
        )
        resolved["collection"] = target
    data = validate_arguments(spec, checked, principal=principal, target=target)
    # A Validator returning ``user`` is a bug, and letting its value outrank the
    # seed silently would be the worse one: the service would act as whoever
    # the arguments named. Refused rather than dropped, so the bug is found.
    seeded = sorted(data.keys() & pool_seeds.reserved)
    if seeded:
        raise ImproperlyConfigured(
            f"The Validator returned the key(s) {seeded}, which dispatch seeds itself. A "
            "validated value must never outrank a seeded one; rename the value."
        )
    pool = call_pool(principal, pool_seeds, {**data, "data": data, **resolved}, progress=progress)
    # Before the affordances, as the Validator is: a refusal of the call itself
    # answers before one describing the row's state.
    # test_a_missing_argument_answers_before_an_affordance fails without it.
    # Only the Validator's parameters reach the service from a caller, so they
    # are all a caller could have filled; with no Validator, nothing is.
    validator = spec.validator
    fillable = validator.parameters().names() if validator is not None else frozenset()
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
    enforce_affordances(spec, pool, instance=resolved.get("instance"), reserved=pool_seeds.reserved)
    return Prepared(principal, target, data, kwargs)


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
    kind: Literal["instance", "list"] = "instance"
    if output_spec is not None:
        pool = call_pool(prepared.principal, pool_seeds, {"result": result})
        value = lookup(
            output_spec,
            pool,
            source=OUTPUT_SOURCE,
            reserved=pool_seeds.reserved,
            after_the_run=True,
        )
        if output_spec.kind is SelectorKind.LIST:
            kind = "list"
    return DispatchResult(
        kind=kind,
        value=value,
        service_result=result,
        instance=prepared.target,
        data=prepared.data,
    )
