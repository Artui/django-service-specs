from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Final

from django.core.exceptions import ImproperlyConfigured
from django.db.models import Exists, Model, OuterRef

from django_service_specs.pool.utils import pool_kwargs
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance_declarer import AffordanceDeclarer
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.types.utils import (
    CALL_CONTEXT,
    PER_CALL_POOL_NAMES,
    affordance_alias,
    is_row_condition,
)

AFFORDANCES_KEY: Final = "affordances"
"""The key each presented object carries its answers under."""

_REASON: Final = "reason"

_MISSING: Final = object()


def ambient_pool(pool: Mapping[str, Any], *, reserved: frozenset[str]) -> dict[str, Any]:
    """The part of a pool an affordance's callable condition may read."""
    return {
        key: value
        for key, value in pool.items()
        if (key in reserved and key not in PER_CALL_POOL_NAMES) or key == CALL_CONTEXT
    }


def with_call_context(
    pool: Mapping[str, Any], call_context: dict[str, Any] | None
) -> dict[str, Any]:
    """``pool`` carrying the call's context: the one passed, else the pool's, else a new one."""
    held = pool.get(CALL_CONTEXT, _MISSING)
    if call_context is None:
        return {**pool, CALL_CONTEXT: {} if held is _MISSING else held}
    if held is not _MISSING and held is not call_context:
        raise ImproperlyConfigured(
            "call_context was passed beside a different call_context in the pool. A call has "
            "one context: pass it once, or pass the same dict the pool carries."
        )
    return {**pool, CALL_CONTEXT: call_context}


def answer_operation_condition(
    when: Callable[..., Any], pool: Mapping[str, Any], *, reserved: frozenset[str]
) -> bool:
    """One callable affordance condition, answered against ``pool`` and read for truth."""
    ambient = ambient_pool(pool, reserved=reserved)
    answer = when(**pool_kwargs(when, ambient))
    if inspect.isawaitable(answer) or inspect.isasyncgen(answer):
        if inspect.iscoroutine(answer):
            answer.close()
        name = getattr(when, "__qualname__", None) or type(when).__name__
        raise ImproperlyConfigured(
            f"The affordance condition {name} answered with an awaitable "
            f"({type(answer).__name__}) where a bool was asked for. A condition is sync-only "
            "and is never awaited, so it is refused rather than read as met; declare it "
            "with def."
        )
    return bool(answer)


def affordance_expression(model: type[Model], when: Any) -> Exists:
    """The SQL answer to one affordance condition, for whichever row it is annotated on."""
    return Exists(model._base_manager.filter(pk=OuterRef("pk")).filter(when))


def split_affordances(
    affordances: Mapping[str, AffordanceDeclarer],
    pool: Mapping[str, Any],
    *,
    reserved: frozenset[str],
) -> tuple[dict[str, Any], dict[str, bool]]:
    """``(row conditions, answered constants)``, both keyed by annotation name."""
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
    """A selector's non-``QuerySet`` result, with each row carrying its answers."""
    if kind is SelectorKind.RETRIEVE:
        if result is None:
            return None
        return _answer_rows([result], row_conditions, constants, source_label)[0]
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
            # ``None`` for a row the answers query did not find, not ``False``.
            setattr(row, alias, flags.get(alias))
        for alias, answer in constants.items():
            setattr(row, alias, answer)
        answered.append(row)
    return answered


def _row_condition_answers(
    model: type[Model], pks: list[Any], row_conditions: Mapping[str, Any]
) -> dict[Any, dict[str, bool]]:
    """Every row condition's answer for every ``pk``, in one query over ``model``."""
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


def rendered_affordances(
    spec: ServiceSpec | SelectorSpec,
) -> Mapping[str, AffordanceDeclarer] | None:
    """The ``affordances`` mapping on whichever selector spec ``spec`` presents through."""
    if isinstance(spec, SelectorSpec):
        return spec.affordances
    nested = spec.output_selector_spec
    return nested.affordances if nested is not None else None


def with_affordances(
    payload: Any, value: Any, affordances: Mapping[str, AffordanceDeclarer], *, many: bool
) -> Any:
    """``payload`` with each presented object carrying its row's answers."""
    if not many:
        return _with_answers(payload, value, affordances)
    return [_with_answers(item, row, affordances) for item, row in zip(payload, value, strict=True)]


def affordance_schema(affordances: Mapping[str, AffordanceDeclarer]) -> dict[str, Any]:
    """The JSON Schema for the ``affordances`` object ``with_affordances`` adds."""
    properties: dict[str, Any] = {}
    for name, service_spec in affordances.items():
        answer: dict[str, Any] = {"available": {"type": "boolean"}}
        codes = [affordance.code for affordance in service_spec.affordances or ()]
        if codes:
            answer["code"] = {"type": "string", "enum": codes}
            answer[_REASON] = {"type": "string"}
        properties[name] = {"type": "object", "properties": answer, "required": ["available"]}
    return {"type": "object", "properties": properties, "required": list(affordances)}


def _with_answers(
    item: Any, row: Any, affordances: Mapping[str, AffordanceDeclarer]
) -> dict[str, Any]:
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
    return {**item, AFFORDANCES_KEY: answer_row_affordances(row, affordances)}


def answer_row_affordances(
    row: Any, affordances: Mapping[str, AffordanceDeclarer]
) -> dict[str, dict[str, Any]]:
    """Each declared name's answer for ``row``, walking its conditions in order."""
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
    """One answer off a row: an attribute on an instance, a key on a mapping."""
    flag: Any = (
        row.get(alias, _MISSING) if isinstance(row, Mapping) else getattr(row, alias, _MISSING)
    )
    if flag is _MISSING:
        raise ImproperlyConfigured(
            f"The row carries no {alias!r} answer. Affordance answers are "
            "computed by the selector spec that declares them; a value that did not come "
            "through that selector has none."
        )
    return flag
