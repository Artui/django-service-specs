"""Helpers every reader of an affordance answers through.

The call refusing an operation, a transport deciding whether to offer it, and a
list reporting it per row all ask the same conditions. Each question is answered
here once, so no two of them can disagree about which names a condition sees,
what counts as met, or which rows a condition on the row lets through.

The per-row answers have two halves, and both live here for the reason
``project_payload`` and ``annotate_output_schema`` sit side by side: they agree
only while they are read together. Dispatch puts the answers on the rows
(``split_affordances``, ``rows_with_affordances``), and presenting reads them
back off each row into the ``affordances`` object a transport serves
(``with_affordances``), which ``affordance_schema`` describes. Nothing on the
presenting side touches a presenter - a payload arrives already presented - so
the object survives whatever renders the fields.

The per-call names, the row-condition test and the answer's alias live in
``types/utils.py`` instead: ``Affordance`` and the specs read them at
construction, and ``types/`` is the one place they can import from without
loading this phase.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any, Final

from django.core.exceptions import ImproperlyConfigured
from django.db.models import Exists, Model, OuterRef

from django_service_specs.pool.resolve_callable_kwargs import resolve_callable_kwargs
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.utils import (
    PER_CALL_POOL_NAMES,
    affordance_alias,
    is_row_condition,
)

AFFORDANCES_KEY: Final = "affordances"
"""The key each presented object carries its answers under."""

_REASON: Final = "reason"

_MISSING: Final = object()


def ambient_pool(pool: Mapping[str, Any], *, reserved: frozenset[str]) -> dict[str, Any]:
    """The part of a pool an affordance's callable condition may read.

    The seeds - ``user``, ``progress`` and whatever the project registered - and
    nothing else. Not the per-call names (the target, the validated input, and
    the values a later step adds), which would make the answer depend on
    attempting the call; and not a client argument spread into the pool, which
    would let the caller decide whether the operation is available. Filtering by
    the reserved set rather than by exclusion is what makes the second hold: a
    spread key is by construction not a seed, because dispatch refuses a
    parameter named after one.

    One definition, so a condition asked at the moment of a call and the same
    condition asked for a list see the same names.
    """
    # Two conjuncts, each held in tests/affordances/test_utils.py:
    # ``test_a_spread_argument_is_not_ambient`` fails without the first, and
    # ``test_a_per_call_name_is_not_ambient_although_it_is_reserved`` without
    # the second.
    return {
        key: value
        for key, value in pool.items()
        if key in reserved and key not in PER_CALL_POOL_NAMES
    }


def answer_operation_condition(
    when: Callable[..., Any], pool: Mapping[str, Any], *, reserved: frozenset[str]
) -> bool:
    """One callable affordance condition, answered against ``pool`` and read for truth.

    Three places ask a condition on nothing in particular: the call, refusing
    it (``enforce_affordances``); a list, projecting it onto every row
    (``split_affordances``); and a transport deciding whether to offer the operation at all
    (``unmet_operation_affordance``). All three answer it here, so they cannot
    disagree about which names the condition sees - the ``ambient_pool`` of
    whatever pool the caller holds, taken here rather than by each caller - nor
    about what counts as met: a callable that returns nothing is unmet in all
    three, not in two of them.
    """
    ambient = ambient_pool(pool, reserved=reserved)
    return bool(when(**resolve_callable_kwargs(when, ambient)))


def affordance_expression(model: type[Model], when: Any) -> Exists:
    """The SQL answer to one affordance condition, for whichever row it is annotated on.

    ``Exists(<the row, narrowed by pk>.filter(when))`` rather than the condition
    inline, for two reasons that both come from where this is spent. Inline, a
    condition spanning a multi-valued relation joins it into the outer query and
    **duplicates the rows** of the list it is annotated on, and an aggregate
    beside it counts across that join. Inside a correlated subquery the outer
    query gains no join at all. And the subquery gives the condition exactly the
    meaning it has in ``Model.objects.filter(when)``, which is the reading an
    author already has for a ``Q``.

    ``_base_manager`` because the subquery only re-finds a row that has already
    been resolved: a default manager that hides rows would answer "unavailable"
    for a row the caller is looking at.

    The single-object check and a list projection both annotate this one
    expression, so the two cannot disagree about any row. Being SQL, it reads the
    table and never a ``prefetch_related`` cache, so a filtered ``Prefetch`` on
    the same relation cannot hide rows from the answer.
    """
    return Exists(model._base_manager.filter(pk=OuterRef("pk")).filter(when))


def split_affordances(
    affordances: Mapping[str, ServiceSpec],
    pool: Mapping[str, Any],
    *,
    reserved: frozenset[str],
) -> tuple[dict[str, Any], dict[str, bool]]:
    """``(row conditions, answered constants)``, both keyed by annotation name.

    A condition on the row is returned as declared, for whichever path evaluates
    it - an annotation on a query, or one query over the rows a selector
    returned - and both build it with ``affordance_expression``, the correlated
    ``Exists`` the single-object check also runs, so every path agrees about
    every row by construction rather than by a test. A callable condition has no
    row to vary with, so it is answered once, here, by the same
    ``answer_operation_condition`` the call is refused by, whatever the selector
    returned.
    """
    row_conditions: dict[str, Any] = {}
    constants: dict[str, bool] = {}
    for name, service_spec in affordances.items():
        for affordance in service_spec.affordances or ():
            alias = affordance_alias(name, affordance.code)
            if is_row_condition(affordance.when):
                row_conditions[alias] = affordance.when
                continue
            constants[alias] = answer_operation_condition(affordance.when, pool, reserved=reserved)
    return row_conditions, constants


def rows_with_affordances(
    result: Any,
    *,
    kind: SelectorKind,
    row_conditions: Mapping[str, Any],
    constants: Mapping[str, bool],
    source_label: str,
) -> Any:
    """A selector's non-``QuerySet`` result, with each row carrying its answers.

    The same answers, under the same ``affordance__<name>__<code>`` names, that
    a ``QuerySet`` result carries as annotations - so presenting reads them the
    same way whichever the selector returned. ``RETRIEVE`` treats the result as
    one row (``None`` passes through); ``LIST`` as an iterable of rows,
    materialised into the list that flows on, so a generator is walked once.

    - **A model instance** gets every row condition answered by one query per
      model class present - see ``_row_condition_answers`` - and the answers
      set as attributes, as an annotation would be.
    - **A mapping** gets a new mapping with the callable answers added; the
      selector's own object is left alone. A condition on the row is refused
      here, because a mapping has no model and no primary key to evaluate one
      against.
    - **Anything else** is refused rather than having attributes written onto it.

    Raises:
        ImproperlyConfigured: A ``LIST`` result is not an iterable of rows, a row
            is neither a model instance nor a mapping, a row condition meets a
            mapping row, or a row condition meets an instance with no primary key.
    """
    if kind is SelectorKind.RETRIEVE:
        if result is None:
            return None
        return _answer_rows([result], row_conditions, constants, source_label)[0]
    # One branch to coverage, so each condition is held by its own case of
    # test_a_list_result_that_is_not_an_iterable_of_rows_is_refused: ``mapping``,
    # ``str`` and ``bytes`` each fail without their member of the tuple (each is
    # iterable, and would be walked as rows), and ``int`` without the second
    # condition.
    if isinstance(result, Mapping | str | bytes) or not isinstance(result, Iterable):
        raise ImproperlyConfigured(
            f"affordances are declared on a LIST spec but {source_label} returned "
            f"{type(result).__name__}, which is neither a QuerySet nor an iterable of rows."
        )
    return _answer_rows(list(result), row_conditions, constants, source_label)


def _answer_rows(
    rows: list[Any],
    row_conditions: Mapping[str, Any],
    constants: Mapping[str, bool],
    source_label: str,
) -> list[Any]:
    by_model: dict[type[Model], list[Any]] = {}
    for row in rows:
        if isinstance(row, Model):
            # One branch to coverage, so each condition is held by its own test:
            # test_an_instance_with_no_primary_key_is_fine_with_only_callable_conditions
            # (the first) and test_a_list_of_instances_costs_one_query_whatever_the_row_count
            # (the second, without which every saved instance is refused).
            if row_conditions and row.pk is None:
                raise ImproperlyConfigured(
                    f"{source_label} returned {row!r}, which has no primary key, and a "
                    "condition on the row is answered by finding the row. Return saved "
                    "instances."
                )
            by_model.setdefault(type(row), []).append(row.pk)
        elif isinstance(row, Mapping):
            if row_conditions:
                raise ImproperlyConfigured(
                    f"{source_label} returned mapping rows, and the affordances declare a "
                    "condition on the row: a mapping has no model and no primary key to "
                    "evaluate one against. Return model instances or a QuerySet, or keep "
                    "only callable conditions."
                )
        else:
            raise ImproperlyConfigured(
                f"{source_label} returned a row of type {type(row).__name__}. Affordance "
                "answers are carried by model instances and mappings; return one of those, "
                "or a QuerySet."
            )
    # Rows whose answers are all callable cost no query:
    # test_only_callable_conditions_spend_no_row_query.
    answers = (
        {
            model: _row_condition_answers(model, pks, row_conditions)
            for model, pks in by_model.items()
        }
        if row_conditions
        else {}
    )
    answered: list[Any] = []
    for row in rows:
        if isinstance(row, Mapping):
            answered.append({**row, **constants})
            continue
        flags = answers.get(type(row), {}).get(row.pk, {})
        for alias in row_conditions:
            # ``None`` for a row the answers query did not find - see
            # ``_row_condition_answers`` for why that is not ``False``.
            setattr(row, alias, flags.get(alias))
        for alias, answer in constants.items():
            setattr(row, alias, answer)
        answered.append(row)
    return answered


def _row_condition_answers(
    model: type[Model], pks: list[Any], row_conditions: Mapping[str, Any]
) -> dict[Any, dict[str, bool]]:
    """Every row condition's answer for every ``pk``, in one query over ``model``.

    Annotated with ``affordance_expression`` - the same expression a
    ``QuerySet`` result is annotated with and the call is checked with - and
    narrowed with ``_base_manager``, because the rows are already in hand and a
    default manager that hides some would answer for fewer of them.

    **A pk the table no longer holds is absent from the result**, and its row
    carries ``None`` for every row condition, not ``False``. The row was
    deleted between the selector returning it and this query, so nothing can
    be done to it - a call against it is refused as not found - and it must not
    read as available. But ``False`` means "fails this condition", and the
    presented answer for a failed condition names its code and reason:
    "already archived" is a false sentence about a row that no longer exists.
    ``None`` is the third answer, "no row to ask", which presents as
    unavailable with no code and no reason. Callable conditions are not about
    the row, and keep their real answers.
    """
    aliases = list(row_conditions)
    found = (
        model._base_manager.filter(pk__in=pks)
        .annotate(
            **{alias: affordance_expression(model, when) for alias, when in row_conditions.items()}
        )
        .values_list("pk", *aliases)
    )
    return {
        pk: {alias: bool(flag) for alias, flag in zip(aliases, flags, strict=True)}
        for pk, *flags in found
    }


def rendered_affordances(spec: ServiceSpec | SelectorSpec) -> Mapping[str, ServiceSpec] | None:
    """The ``affordances`` mapping on whichever selector spec ``spec`` presents through.

    A ``SelectorSpec`` carries its own. A ``ServiceSpec`` presents its output
    selector's rows, so it is that selector's - and its *own* ``affordances``
    are the conditions it is checked against, a different declaration that is
    never presented, which is why this dispatches on the class rather than
    reading the attribute.
    """
    if isinstance(spec, SelectorSpec):
        return spec.affordances
    nested = spec.output_selector_spec
    return nested.affordances if nested is not None else None


def with_affordances(
    payload: Any, value: Any, affordances: Mapping[str, ServiceSpec], *, many: bool
) -> Any:
    """``payload`` with each presented object carrying its row's answers.

    ``value`` is what was presented: the row, or for ``many`` the materialised
    rows in the order they were presented, so the two can be walked together.
    Callers skip a ``None`` value, which is not a row and has nothing to report.

    Raises:
        ImproperlyConfigured: A presented item is not an object to add a key to;
            it already has an ``affordances`` key, which the answers would
            overwrite; or its row carries no answer, because the selector that
            produced it was not the one declaring them.
    """
    if not many:
        return _with_answers(payload, value, affordances)
    return [_with_answers(item, row, affordances) for item, row in zip(payload, value, strict=True)]


def affordance_schema(affordances: Mapping[str, ServiceSpec]) -> dict[str, Any]:
    """The JSON Schema for the ``affordances`` object ``with_affordances`` adds.

    One property per declared name, each an object whose ``available`` is
    always present and whose ``code`` - enumerated from the declaration, so a
    client can switch on it exhaustively - and ``reason`` appear only when it
    is ``false``, and not even then for a row that no longer exists. The same
    for every audience: a browser and a model both read the reason, and both
    branch, if at all, on the code.
    """
    properties: dict[str, Any] = {}
    for name, service_spec in affordances.items():
        answer: dict[str, Any] = {"available": {"type": "boolean"}}
        codes = [affordance.code for affordance in service_spec.affordances or ()]
        if codes:
            answer["code"] = {"type": "string", "enum": codes}
            answer[_REASON] = {"type": "string"}
        properties[name] = {"type": "object", "properties": answer, "required": ["available"]}
    return {"type": "object", "properties": properties, "required": list(affordances)}


def _with_answers(item: Any, row: Any, affordances: Mapping[str, ServiceSpec]) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        raise ImproperlyConfigured(
            "affordances are projected into each presented object, and this spec's presenter "
            f"returned {type(item).__name__}. Present each row as an object."
        )
    if AFFORDANCES_KEY in item:
        raise ImproperlyConfigured(
            f"The presented object already has an {AFFORDANCES_KEY!r} key, which the declared "
            "affordances would overwrite. Rename the output field."
        )
    return {**item, AFFORDANCES_KEY: _answers(row, affordances)}


def _answers(row: Any, affordances: Mapping[str, ServiceSpec]) -> dict[str, dict[str, Any]]:
    """Each declared name's answer for ``row``, walking its conditions in order.

    ``True`` continues. ``False`` is the first unmet condition, reported with
    its code and reason. ``None`` is a condition on the row asked of a row that
    no longer exists: the answer is unavailable, with no code and no reason,
    because no condition's sentence is true of a missing row. It stops the walk
    like any refusal, so an unmet callable declared *earlier* still reports its
    own sentence, which is true either way.
    """
    answers: dict[str, dict[str, Any]] = {}
    for name, service_spec in affordances.items():
        answer: dict[str, Any] = {"available": True}
        for affordance in service_spec.affordances or ():
            flag = _flag(row, affordance_alias(name, affordance.code))
            if flag is None:
                answer = {"available": False}
                break
            if not flag:
                answer = {"available": False, "code": affordance.code, _REASON: affordance.reason}
                break
        answers[name] = answer
    return answers


def _flag(row: Any, alias: str) -> Any:
    """One answer off a row: an attribute on an instance, a key on a mapping.

    The same names whichever way the answers got there - a queryset
    annotation, or ``rows_with_affordances`` answering rows a selector returned
    directly.
    """
    flag: Any = (
        row.get(alias, _MISSING) if isinstance(row, Mapping) else getattr(row, alias, _MISSING)
    )
    if flag is _MISSING:
        raise ImproperlyConfigured(
            f"The presented row carries no {alias!r} answer. Affordance answers are "
            "computed by the selector spec that declares them; a value that did not come "
            "through that selector has none."
        )
    return flag
