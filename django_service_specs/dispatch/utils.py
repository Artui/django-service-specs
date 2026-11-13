from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Mapping
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
from django_service_specs.dispatch.call_seeds import CallSeeds
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.grant import Grant
from django_service_specs.dispatch.relax_partial import relax_partial
from django_service_specs.output.presentation_context import PresentationContext
from django_service_specs.parameters.check_arguments import check_arguments
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.parameters.utils import length_problem
from django_service_specs.pool.call_seeds import CALL_SEEDS
from django_service_specs.pool.null_progress import null_progress
from django_service_specs.pool.pool_seeds import PoolSeeds
from django_service_specs.pool.provider_keys import provider_keys
from django_service_specs.pool.seeded_pool import seeded_pool
from django_service_specs.pool.utils import (
    deferred_progress,
    only_seeds,
    resolve_progress,
    resolve_provider,
)
from django_service_specs.selectors.is_queryset import is_queryset
from django_service_specs.selectors.materialize_retrieve import materialize_retrieve
from django_service_specs.selectors.run_selector import run_selector
from django_service_specs.selectors.utils import apply_shaping, call_keywords, required_keywords
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.is_async import is_async
from django_service_specs.types.progress_reporter import ProgressReporter
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.types.unknown_arguments import UnknownArguments
from django_service_specs.types.unset import UNSET
from django_service_specs.types.utils import CALL_CONTEXT, CALL_SEEDS_NOTE, SHAPES, callable_name
from django_service_specs.validation.validated import Validated
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator
from django_service_specs.validation.validator_parameters import validator_parameters

NOT_FOUND = DispatchResult(kind="not_found")
"""A required row that does not exist. Frozen, so one instance serves every call."""


class ListNotFound(Exception):
    """A LIST selector's own ``Http404``, raised by ``lookup`` for its caller to answer."""


@dataclass(frozen=True)
class Overlay:
    """A call's own keywords beneath the spec's ``kwargs`` provider: ``extra_kwargs``."""

    kwargs: Mapping[str, Any] = field(default_factory=dict)


NO_OVERLAY = Overlay()


def refuse_overlaid_parameters(
    spec: ServiceSpec | SelectorSpec, declared: Parameters, overlay: Overlay
) -> None:
    """Refuse an ``extra_kwargs`` key that would stand in for a caller's argument."""
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
    """``overlay`` beneath ``provided``, what the spec's own ``provider`` answered."""
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
    """A service spec that has passed every step before its run."""

    principal: Any
    target: Any
    data: Any
    kwargs: dict[str, Any]
    ambient: Mapping[str, Any]
    call_context: dict[str, Any]
    shapes: Mapping[str, Any]
    early_seeds: Mapping[str, Any]


@dataclass(frozen=True)
class CheckKeywords:
    """What a call offers its permission checks by name besides ``arguments``."""

    call_context: dict[str, Any] = field(default_factory=dict)
    seeds: dict[str, Any] = field(default_factory=dict)

    def offered(self) -> dict[str, Any]:
        """The keywords each ``authorize`` function is offered: the context and the seeds."""
        return {"call_context": self.call_context, "seeds": self.seeds}


def shapes_sent(spec: ServiceSpec | SelectorSpec, checked: Mapping[str, Any]) -> Mapping[str, Any]:
    """What the caller sent for ``spec``'s ``shapes``, read-only: the presenter's ``shapes``."""
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
    """``seeded_pool``, taking the seeds already resolved for a check as they are."""
    seeds = pool_seeds if not early else only_seeds(pool_seeds, pool_seeds.names - early.keys())
    pool = seeded_pool(user=principal, seeds=seeds, call_context=call_context, progress=progress)
    pool.update(early)
    return pool


@dataclass(frozen=True)
class _CheckedRows:
    """A many spec's list after the shape check: each row's checked arguments, or its refusal."""

    rows: dict[int, dict[str, Any]]
    errors: dict[int, Any]


def checks_arguments(checked: Mapping[str, Any]) -> Mapping[str, Any]:
    """What a permission check declaring ``arguments`` is handed: ``checked``, read-only."""
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
    carried: CallSeeds | None,
) -> tuple[dict[str, Any], Grant]:
    """Steps one and two: the checked arguments, and the grant the call runs under."""
    refuse_deactivated(principal)
    declared = spec.parameters(call_context=keywords.call_context)
    parameters = seat_seed_named(
        spec,
        declared,
        declared if parameters is None else parameters,
        pool_seeds,
        call_context=keywords.call_context,
    )
    refuse_overlaid_parameters(spec, declared, overlay)
    checked = shape_check(
        spec,
        parameters,
        arguments,
        unknown_arguments=unknown_arguments,
        call_context=keywords.call_context,
    )
    if carried is None:
        keywords.seeds.update(
            seeds_for_checks(
                spec, principal, pool_seeds, QUESTIONS, call_context=keywords.call_context
            )
        )
    else:
        keywords.seeds.update(
            carried.values_for(spec, principal, keywords.call_context, pool_seeds)
        )
    granted = authorize(
        spec,
        principal,
        grant=grant,
        arguments=checks_arguments(checked),
        **keywords.offered(),
    )
    if settle_rows:
        for name, value in checked.items():
            if isinstance(value, _CheckedRows):
                if value.errors:
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
    *,
    call_context: dict[str, Any] | None = None,
) -> Parameters:
    """``parameters`` less the reads a registered seed fills, refusing a name no seed may share."""
    seated, taken = split_seed_named(spec, declared, pool_seeds, call_context=call_context)
    if taken:
        raise ImproperlyConfigured(seed_named_refusal(spec, taken, pool_seeds))
    if seated:
        return Parameters.of(*(param for param in parameters if param.name not in seated))
    return parameters


def seed_named_refusal(
    spec: ServiceSpec | SelectorSpec, taken: frozenset[str], pool_seeds: PoolSeeds
) -> str:
    """Why ``spec`` is refused for declaring ``taken``: the second set of ``split_seed_named``."""
    hint = "" if taken <= pool_seeds.names else CALL_SEEDS_NOTE
    return (
        f"{type(spec).__name__} declares the parameter(s) {sorted(taken)}, which a "
        "registered pool seed occupies. An argument must never meet a seed in one pool; "
        f"rename the parameter.{hint}"
    )


def split_seed_named(
    spec: ServiceSpec | SelectorSpec,
    declared: Parameters,
    pool_seeds: PoolSeeds,
    *,
    call_context: dict[str, Any] | None = None,
) -> tuple[frozenset[str], frozenset[str]]:
    """Of ``declared``'s names, the reads a registered seed fills and those refused."""
    shared = declared.names() & (pool_seeds.reserved | CALL_SEEDS)
    seated = shared & frozenset(
        param.name for _, reads in read_seats(spec) for param in reads if param.reflected
    )
    return (
        seated,
        shared
        - seated
        - seed_named_fields(spec, pool_seeds.names | CALL_SEEDS, call_context=call_context),
    )


def seed_named_fields(
    spec: ServiceSpec | SelectorSpec,
    names: frozenset[str],
    *,
    call_context: dict[str, Any] | None = None,
) -> frozenset[str]:
    """The top-level Validator fields of ``spec`` named in ``names``, never the pool's."""
    if isinstance(spec, ServiceSpec) and spec.validator is not None and not spec.many:
        return validator_parameters(spec.validator, call_context=call_context).names() & names
    return frozenset()


def shape_check(
    spec: ServiceSpec | SelectorSpec,
    parameters: Parameters,
    arguments: Mapping[str, Any],
    *,
    unknown_arguments: UnknownArguments,
    call_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """``check_arguments`` over ``parameters``, leaving out what the server fills or may fill."""
    owned, reached = server_filled(spec)
    parameters = relax_partial(spec, parameters)
    if isinstance(spec, ServiceSpec) and spec.validator is not None:
        fields, fields_reached = reach(
            spec.input_data, validator_parameters(spec.validator, call_context=call_context)
        )
        if spec.many and spec.many_argument in parameters.names():
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
    """``checked`` less every key a typed provider fills."""
    return {name: value for name, value in checked.items() if name not in owned}


def server_filled(spec: ServiceSpec | SelectorSpec) -> tuple[frozenset[str], frozenset[str]]:
    """The reads a ``kwargs`` provider fills, or may fill, where its values reach them."""
    owned: frozenset[str] = frozenset()
    reached: frozenset[str] = frozenset()
    demanded: frozenset[str] = frozenset()
    for provider, reads in read_seats(spec):
        filled, may_fill = reach(provider, reads)
        owned |= filled
        reached |= may_fill
        demanded |= (reads.names() - filled) & _requires(provider)
    if isinstance(spec, ServiceSpec):
        filled, _ = reach(spec.kwargs, spec.reads)
        demanded |= (spec.reads.names() - filled) & _requires(spec.input_data)
    return owned, reached - demanded


def _requires(provider: Callable[..., Any] | None) -> frozenset[str]:
    """The keywords ``provider`` takes by name with no default; none if unreadable."""
    if provider is None:
        return frozenset()
    try:
        return frozenset(required_keywords(provider))
    except (ValueError, TypeError):
        return frozenset()


def read_seats(
    spec: ServiceSpec | SelectorSpec,
) -> list[tuple[Callable[..., Any] | None, Parameters]]:
    """Each selector or service seat of ``spec``: its ``kwargs`` provider and the reads it feeds."""
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
    """The names in ``parameters`` that ``provider`` is annotated to fill."""
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
    """The top level of a ``many`` call checked here, and each row checked on its own."""
    value = arguments.get(name) if isinstance(arguments, Mapping) else None
    the_list = next(param for param in parameters if param.name == name)
    rows = _relaxed(cast(Parameters, the_list.items), reached_in_rows)
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
        try:
            cleaned[index] = _without(
                check_arguments(rows, row, unknown_arguments=unknown_arguments), owned_in_rows
            )
        except InvalidArguments as refused:
            errors[index] = refused.detail
    checked[name] = _CheckedRows(cleaned, errors)
    return checked


def _relaxed(parameters: Parameters, reached: frozenset[str]) -> Parameters:
    """``parameters`` with the ones a provider fills or may fill optional, at the top level only."""
    return Parameters.of(
        *(
            replace(param, required=False) if param.name in reached else param
            for param in parameters
        )
    )


def _refuse_absent(parameters: Parameters, pool: Mapping[str, Any]) -> None:
    """Refuse every required parameter of the call that is absent from ``pool``."""
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
    """The pool a selector is called from: the base pool, its ``reads``, then its ``kwargs``."""
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
    """A selector's run keywords, with the reporter under ``progress`` where taken."""
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
    """A ``kwargs`` provider's entries, refusing one that names a key dispatch seeds."""
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
    """The reporter ``run`` reports to: the transport's, beside the spec's ``progress_reporter``."""
    resolve = resolve_progress if is_async(run) else deferred_progress
    reporter = resolve(provider, base, transport=transport)
    return null_progress if reporter is None else reporter


def run_preconditions(
    spec: ServiceSpec | SelectorSpec, pool: Mapping[str, Any], *, fillable: frozenset[str]
) -> None:
    """Call each of ``spec``'s ``preconditions`` from ``pool``, in declaration order."""
    for precondition in spec.preconditions or ():
        sync_result(
            precondition(**call_keywords(precondition, pool, fillable=fillable)),
            asked=f"The precondition {callable_name(precondition)}",
            seat="A precondition",
        )


def sync_result(answer: Any, *, asked: str, seat: str) -> Any:
    """Return what a sync-only callable answered, refusing an answer that is still to be awaited."""
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
    """The base pool, then this call's own entries on top of it: the output selector's pool."""
    pool = seeded_base(
        principal, progress=progress, pool_seeds=pool_seeds, early=early, call_context=call_context
    )
    pool.update(entries)
    return pool


def reraise_unless_retrieve(
    selector_spec: SelectorSpec, error: ObjectDoesNotExist | Http404
) -> None:
    """Called from an ``except (ObjectDoesNotExist, Http404)``: what it means for this selector."""
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
    """Shape what a selector returned, answer its affordances, and collapse a RETRIEVE."""
    if raw is None and selector_spec.kind is SelectorKind.LIST and selector_spec.allow_none:
        return []
    if isinstance(raw, BaseManager):
        raw = raw.all()
    annotations: Mapping[str, Any] | None = selector_spec.annotations
    row_conditions: dict[str, Any] = {}
    constants: dict[str, bool] = {}
    queryset = is_queryset(raw)
    if selector_spec.affordances is not None:
        if queryset and selector_spec.row_object is not None:
            raise ImproperlyConfigured(
                f"{source} returned a QuerySet, whose rows are answered in SQL as the model "
                "itself, and SelectorSpec.row_object is declared. Return the wrapped rows, or "
                "drop row_object."
            )
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
    if selector_spec.affordances is not None and not queryset:
        shaped = rows_with_affordances(
            shaped,
            kind=selector_spec.kind,
            row_conditions=row_conditions,
            constants=constants,
            source_label=source,
            row_object=selector_spec.row_object,
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
    """Call a selector from sync code and settle its return: the rows, the row, or ``None``."""
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
        if isinstance(error, Http404) and selector_spec.kind is SelectorKind.LIST:
            if after_the_run:
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
    """Step four for a selector spec, its ``preconditions``, and its result."""
    grant = replace(grant, target_checked=False)
    handed = checks_arguments(checked)
    fillable = spec.reads.names()
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


def asks_scope_of_nothing(spec: ServiceSpec | SelectorSpec) -> bool:
    """Whether a call asks ``spec``'s scope question of nothing."""
    return isinstance(spec, ServiceSpec) and spec.target_selector_spec() is None


def target_entry(spec: ServiceSpec, target: Any) -> dict[str, Any]:
    """``target`` under the pool name a service spec hands it to its service as."""
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
    """Steps three and four for a service spec: its target, found and checked."""
    if target is UNSET:
        grant = replace(grant, target_checked=False)
    offered = keywords.offered()
    handed = checks_arguments(checked)
    no_shapes: Mapping[str, Any] = MappingProxyType({})
    instance_spec = spec.instance_selector_spec
    collection_spec = spec.collection_selector_spec
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
                return NOT_FOUND
        authorize_scope(spec, principal, target, grant=grant, arguments=handed, **offered)
        return target_entry(spec, target)
    if target is not UNSET and target is not None:
        raise TypeError(
            "dispatch() was handed a target= for a ServiceSpec that declares no target "
            "selector. A create acts on no existing row; pass target=None or nothing."
        )
    authorize_scope(spec, principal, None, grant=grant, arguments=handed, **offered)
    return target_entry(spec, None)


def refuse_seeds(seeds: Any, grant: Grant | None, *, principal_id: Any = None) -> None:
    """Refuse ``seeds=`` that cannot be a prelude's, before anything runs."""
    if seeds is None:
        return
    if not isinstance(seeds, CallSeeds):
        raise TypeError(
            "seeds= takes the CallSeeds that check_call() or resolve_target() hands back on "
            "its .seeds, or resolve_seeds() returns; "
            f"got {type(seeds).__name__}."
        )
    if grant is None:
        raise TypeError(
            "seeds= is handed on with the grant= its prelude returned beside it; pass both."
        )
    if principal_id is not None:
        raise TypeError(
            "seeds= cannot cover a principal adispatch() resolves from principal_id=; "
            "pass the principal= its prelude was handed."
        )


def refuse_target(spec: ServiceSpec | SelectorSpec, target: Any) -> None:
    """Refuse ``target=`` where nothing is looked up, before anything runs."""
    if target is UNSET:
        return
    if isinstance(spec, SelectorSpec):
        raise TypeError(
            "target= is a ServiceSpec's, standing in for its target selector's lookup; "
            "a SelectorSpec's selector is its run."
        )
    if spec.many and spec.collection_selector_spec is None:
        raise TypeError(
            "target= stands in for a target selector's lookup, and a many spec with no "
            "collection_selector_spec resolves no target: its rows are the call's arguments."
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
    """Step five: the Validator's result, on only the arguments it declares."""
    validator = spec.validator
    if validator is None:
        return Validated(values={}, data={})
    declared = validator_parameters(validator, call_context=call_context).names()
    context = ValidationContext(
        principal,
        target,
        partial=spec.partial,
        ambient=ambient,
        resolved=MappingProxyType(dict(resolved)),
        call_context=call_context,
    )
    relaxed = (
        relax_partial(spec, spec.parameters(call_context=call_context))
        if provider_answered
        else Parameters.of()
    )
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
    """``validated_many()`` on the rows that passed, one refusal per failing row."""
    declared = validator_parameters(validator, call_context=context.call_context).names()
    errors = dict(checked.errors)
    rows: dict[int, dict[str, Any]] = {}
    for index, row in checked.rows.items():
        merged = {**row, **server_input}
        try:
            _refuse_absent(row_parameters, merged)
        except InvalidArguments as refused:
            errors[index] = refused.detail
            continue
        rows[index] = {key: value for key, value in merged.items() if key in declared}
    checked = _CheckedRows(rows, errors)
    try:
        validated = validator.validated_many(rows, context, many_argument=name)
    except InvalidArguments as refused:
        raise InvalidArguments({name: _list_node({**checked.errors, **refused.detail})}) from None
    if checked.errors:
        raise InvalidArguments({name: _list_node(checked.errors)})
    if validated.values.keys() != {name}:
        raise ImproperlyConfigured(
            f"The Validator's validated_many() returned the value(s) "
            f"{sorted(validated.values)} for a many call; it returns the rows' values under "
            f"{name!r} alone."
        )
    return validated


def _list_node(errors: Mapping[Any, Any]) -> dict[Any, Any]:
    """A list's refusals in reading order: each row by index, then the list's own message."""
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
    carried: CallSeeds | None,
    target: Any = UNSET,
    overlay: Overlay = NO_OVERLAY,
) -> Prepared | DispatchResult:
    """Steps one to six for a service spec: its preconditions and run keywords."""
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
        carried=carried,
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
    target = next(iter(resolved.values()), None)
    reserved = pool_seeds.reserved
    provided = reserved | CALL_SEEDS
    base = seeded_base(
        principal,
        progress=progress,
        pool_seeds=pool_seeds,
        early=keywords.seeds,
        call_context=call_context,
    )
    ambient = MappingProxyType(base)
    shapes = shapes_sent(spec, checked)
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
    fields = seed_named_fields(spec, pool_seeds.names | CALL_SEEDS, call_context=call_context)
    spread = {name: value for name, value in values.items() if name not in fields}
    seeded = sorted(spread.keys() & provided)
    if seeded:
        raise ImproperlyConfigured(
            f"The Validator returned the key(s) {seeded}, which dispatch seeds itself. A "
            "validated value must never outrank a seeded one; rename the value."
        )
    named = provided | values.keys() | spec.parameters(call_context=call_context).names()
    bound = sorted(validated.pool.keys() & named)
    if bound:
        raise ImproperlyConfigured(
            f"The Validator bound the key(s) {bound}, which dispatch seeds, the Validator "
            "returned as a value, or the spec declares as a parameter. A value bound for "
            "the call needs a name of its own."
        )
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
    _refuse_absent(spec.reads, pool)
    validator = spec.validator
    asked = (
        validator_parameters(validator, call_context=call_context).names()
        if validator is not None and not spec.partial and not spec.many
        else frozenset()
    )
    fillable = (declared_reads | asked) - checked.keys()
    kwargs = call_keywords(spec.service, pool, fillable=fillable)
    enforce_affordances(
        spec,
        pool,
        instance=resolved.get("instance"),
        reserved=reserved,
        call_context=call_context,
    )
    run_preconditions(spec, pool, fillable=fillable)
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
    """The output selector, if declared, and the service spec's result."""
    if getattr(prepared.target, "_prefetched_objects_cache", None):
        prepared.target._prefetched_objects_cache = {}
    output_spec = spec.output_selector_spec
    value = result
    lists = spec.many or spec.returns_many
    kind: Literal["instance", "list"] = "list" if lists and result is not None else "instance"
    if output_spec is None and kind == "list":
        _check_service_rows(spec, result)
    if output_spec is not None:
        pool = call_pool(
            prepared.principal,
            pool_seeds,
            {
                "instance": result,
                "result": result,
                CALL_CONTEXT: prepared.call_context,
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


def _check_service_rows(spec: ServiceSpec, value: Any) -> None:
    """Refuse a list-presenting service's return that is not a set of rows."""
    if isinstance(value, Mapping | str | bytes) or not isinstance(value, Iterable):
        remedy = (
            "Return the rows, or drop returns_many to present one value."
            if spec.returns_many
            else "Return the rows, or None to present nothing."
        )
        raise ImproperlyConfigured(
            f"{callable_name(spec.service)} is declared to return a list of rows "
            f"({'returns_many' if spec.returns_many else 'many'}) and returned "
            f"{type(value).__name__}, which is not a set of rows. {remedy} "
            "The service has already run, so its write stands."
        )


def server_arguments_label(spec: ServiceSpec | SelectorSpec) -> str:
    """``spec`` as a ``ServerArguments`` refusal names it: its kind and its callable."""
    fn = spec.service if isinstance(spec, ServiceSpec) else spec.selector
    return f"{type(spec).__name__} for {callable_name(fn)}"


def checked_server_values(
    spec: ServiceSpec | SelectorSpec, parameters: Parameters, values: Mapping[str, Any]
) -> dict[str, Any]:
    """A binding's ``values``, each checked against its own parameter."""
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
