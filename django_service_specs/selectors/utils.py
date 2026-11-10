from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any, Final

from django.core.exceptions import ImproperlyConfigured
from django.db.models import IntegerField
from django.utils.translation import gettext

from django_service_specs.adapters.filters.filter_set_parameters import filter_set_parameters
from django_service_specs.adapters.filters.utils import import_django_filters, range_suffixes
from django_service_specs.parameters.coded_message import CodedMessage
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.utils import (
    WIDEST_INTEGER,
    choices_past_their_columns,
    coded_messages,
    integer_range_refusal,
    path_column,
)
from django_service_specs.pool.utils import pool_kwargs
from django_service_specs.selectors.is_queryset import is_queryset
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.types.utils import CALL_CONTEXT

_NAMED: Final = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
"""The parameter kinds a pool fills by name, and so the only ones it can leave unfilled."""


def required_keywords(fn: Callable[..., Any]) -> tuple[str, ...]:
    """The parameters of ``fn`` a pool must fill, in signature order: by name, with no default."""
    return tuple(
        name
        for name, param in inspect.signature(fn).parameters.items()
        if param.kind in _NAMED and param.default is inspect.Parameter.empty
    )


def call_keywords(
    fn: Callable[..., Any], pool: Mapping[str, Any], *, fillable: frozenset[str]
) -> dict[str, Any]:
    """The keywords ``fn`` is called with, refusing a parameter the caller left unfilled."""
    missing = [name for name in required_keywords(fn) if name not in pool and name in fillable]
    if missing:
        raise InvalidArguments(
            {
                name: [CodedMessage(gettext("This field is required."), "required")]
                for name in missing
            }
        )
    return pool_kwargs(fn, pool)


def apply_shaping(
    queryset: Any,
    spec: SelectorSpec,
    pool: Mapping[str, Any],
    *,
    annotations: Mapping[str, Any] | None,
    source_label: str,
    fillable: frozenset[str],
) -> Any:
    """``shape_queryset``, with the annotations it applies named by the caller."""
    if (
        spec.select_related is None
        and spec.prefetch_related is None
        and annotations is None
        and spec.extend_queryset is None
        and spec.filter_set is None
    ):
        return queryset
    if not is_queryset(queryset):
        raise ImproperlyConfigured(
            "select_related / prefetch_related / annotations / extend_queryset "
            f"/ filter_set are set on the spec but {source_label} returned "
            f"{type(queryset).__name__}, which is not a Django QuerySet. Drop "
            "the shaping fields or have the callable return a QuerySet."
        )
    if spec.select_related is not None:
        queryset = queryset.select_related(*spec.select_related)
    if spec.prefetch_related is not None:
        queryset = queryset.prefetch_related(*spec.prefetch_related)
    if annotations is not None:
        queryset = queryset.annotate(**annotations)
    if spec.extend_queryset is not None:
        extend_pool = {**pool, "queryset": queryset}
        queryset = _settled(
            spec.extend_queryset,
            spec.extend_queryset(
                **call_keywords(spec.extend_queryset, extend_pool, fillable=fillable)
            ),
        )
    if spec.filter_set is not None:
        queryset = _filtered(spec.filter_set, queryset, pool)
    return queryset


def _settled(extend_queryset: Callable[..., Any], queryset: Any) -> Any:
    """``extend_queryset``'s return, refusing one that is still to be awaited."""
    if inspect.isawaitable(queryset) or inspect.isasyncgen(queryset):
        if inspect.iscoroutine(queryset):
            queryset.close()
        name = getattr(extend_queryset, "__qualname__", None) or type(extend_queryset).__name__
        raise ImproperlyConfigured(
            f"extend_queryset {name} answered with an awaitable ({type(queryset).__name__}) "
            "where a queryset was asked for. It is called from sync code and never "
            "awaited, so the value is refused rather than shaped; declare it with def "
            "and return the queryset."
        )
    return queryset


def _filtered(filter_set: Any, queryset: Any, pool: Mapping[str, Any]) -> Any:
    """``queryset`` narrowed by ``filter_set``, from the arguments its filters read."""
    seen = {name: pool[name] for name in ("request", CALL_CONTEXT) if name in pool}
    asked = pool_kwargs(filter_set, seen)
    bound = filter_set(
        **({"request": asked["request"]} if "request" in asked else {}),
        data=_filter_data(filter_set, pool),
        queryset=queryset,
    )
    beyond = _choices_past_their_columns(bound)
    if beyond or not bound.is_valid():
        errors = {**bound.errors.as_data(), **beyond}
        raise InvalidArguments({name: coded_messages(found) for name, found in errors.items()})
    past = _past_their_columns(bound, queryset)
    if past:
        raise InvalidArguments(past)
    return bound.qs


def _choices_past_their_columns(bound: Any) -> dict[str, Any]:
    """Each model choice filter sent a key no row's column can hold, taken off ``bound``'s form."""
    if not isinstance(bound, import_django_filters().FilterSet):
        return {}
    beyond = choices_past_their_columns(bound.form)
    for name in beyond:
        del bound.form.fields[name]
    return beyond


def _past_their_columns(bound: Any, queryset: Any) -> dict[str, Any]:
    """Each argument holding a number no integer column can hold, and its refusal."""
    refusals: dict[str, Any] = {}
    if not isinstance(bound, import_django_filters().FilterSet):
        return refusals
    for name, filter_obj in bound.filters.items():
        if filter_obj.method is not None:
            continue
        column = path_column(queryset.model, filter_obj.field_name)
        if not isinstance(column, IntegerField) or not getattr(
            column.get_lookup(filter_obj.lookup_expr), "prepare_rhs", False
        ):
            continue
        for key, index, value in _sent(name, filter_obj, bound.form.cleaned_data.get(name)):
            try:
                number = column.get_prep_value(value)
            except (TypeError, ValueError):
                continue
            refusal = integer_range_refusal(number, WIDEST_INTEGER)
            if refusal is None:
                continue
            if index is None:
                refusals[key] = coded_messages([refusal])
            else:
                refusals.setdefault(key, {})[index] = coded_messages([refusal])
    return refusals


def _sent(name: str, filter_obj: Any, value: Any) -> list[tuple[str, int | None, Any]]:
    """Each value a filter's cleaned ``value`` holds, with the argument it came in."""
    if isinstance(value, slice):
        keyed = [
            (f"{name}_{suffix}", None, end)
            for suffix, end in zip(
                range_suffixes(filter_obj), (value.start, value.stop), strict=False
            )
        ]
    elif isinstance(value, list):
        keyed = [(name, index, element) for index, element in enumerate(value)]
    else:
        keyed = [(name, None, value)]
    return [entry for entry in keyed if entry[2] is not None]


def _filter_data(filter_set: Any, pool: Mapping[str, Any]) -> dict[str, Any]:
    """The pool's value for each name ``filter_set``'s filters read, as django-filter reads it."""
    names = filter_set_parameters(filter_set).names()
    data = {name: value for name, value in pool.items() if name in names}
    if not data:
        return data
    module = import_django_filters()
    for name, filter_obj in filter_set.base_filters.items():
        value = data.get(name)
        if isinstance(filter_obj, module.BaseCSVFilter) and isinstance(value, list):
            data[name] = ",".join(str(element) for element in value)
    return data
