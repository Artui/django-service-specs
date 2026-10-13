"""Private selector-dispatch helpers, shared across ``selectors/``.

Not exported from ``selectors/__init__.py``. These are used by
``shape_queryset`` and by the dispatch core. ``call_keywords`` binds the
service as well as each selector, and lives here because ``extend_queryset``
is bound by it too, inside ``apply_shaping``.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any, Final

from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db.models import ForeignKey
from django.db.models.constants import LOOKUP_SEP
from django.utils.translation import gettext

from django_service_specs.filters.filter_set_parameters import filter_set_parameters
from django_service_specs.filters.utils import import_django_filters, range_suffixes
from django_service_specs.parameters.coded_message import CodedMessage
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.utils import coded_messages
from django_service_specs.pool.resolve_callable_kwargs import resolve_callable_kwargs
from django_service_specs.relations.utils import integer_column_range, integer_range_refusal
from django_service_specs.selectors.is_queryset import is_queryset
from django_service_specs.specs.selector_spec import SelectorSpec

_NAMED: Final = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
"""The parameter kinds a pool fills by name, and so the only ones it can leave unfilled."""


def call_keywords(
    fn: Callable[..., Any], pool: Mapping[str, Any], *, fillable: frozenset[str]
) -> dict[str, Any]:
    """The keywords ``fn`` is called with, refusing a parameter the caller left unfilled.

    ``resolve_callable_kwargs`` forwards only what the pool has, so a
    parameter with no default that the call left out - an optional read the
    caller did not send, a Validator parameter the caller left out - reached
    the callable as a ``TypeError``. It is refused before the call instead, as
    ``InvalidArguments`` keyed by the parameter, in the shape check's own
    wording for an argument left out.

    **Only where a caller could have filled it.** ``fillable`` is the names
    this call site lets a caller send: a selector's ``reads``, for the
    selector and its ``extend_queryset`` alike, or the service's Validator's
    parameters the caller left out, which are none without a Validator.
    ``shape_queryset`` passes none, because a transport shaping rows itself
    bound no arguments
    (test_a_read_the_pool_lacks_is_the_callable_s_own_error). The argument
    set is closed, so any other name can never arrive - REJECT refuses it as
    unknown, IGNORE drops it - and one the caller sent and the Validator did
    not hand back under that name has already arrived. Refusing either as
    missing would ask for a value the caller cannot send or already did,
    which a client reading ``InvalidArguments`` as its own mistake retries.
    It is the declaration's error, and is left to raise as the callable's
    own ``TypeError``. Decided at the call rather than when
    the spec is declared, because a registered seed may fill such a
    parameter, and the seeds are known only at dispatch.

    A parameter is refused only if it is filled by name, has no default, is
    not in the pool, and is one a caller could fill. No reserved name needs
    excluding, because none is ever fillable: a read or Validator parameter
    named after one of the dispatcher's own is refused as it is declared or
    assembled (``check_reserved``), and one named after a registered seed by
    ``open_call`` (test_a_spec_declaring_a_registered_seed_s_name_is_refused).

    One branch to coverage, so each condition is held by its own test:
    test_a_callable_taking_the_whole_pool_is_never_missing_anything,
    test_a_positional_only_parameter_is_not_reported and
    test_a_var_positional_parameter_is_never_missing (the kind: ``**kwargs``
    takes whatever arrives, a positional-only parameter is never passed by
    name, and ``*args`` needs nothing, so no caller value fills any of them),
    test_a_defaulted_parameter_is_never_missing (the default),
    test_an_optional_read_a_selector_requires_is_refused_when_not_sent (the
    pool: without it a sent read is refused too), and
    test_a_selector_parameter_no_read_declares_is_the_author_s_error with
    test_a_service_parameter_no_validator_declares_is_the_author_s_error (the
    caller's reach).
    """
    missing = [
        name
        for name, param in inspect.signature(fn).parameters.items()
        if param.kind in _NAMED
        and param.default is inspect.Parameter.empty
        and name not in pool
        and name in fillable
    ]
    if missing:
        # Translated where it is raised, spelled and coded as the shape check
        # refuses an absent required argument, so a caller reads one refusal
        # whichever of the two answered.
        raise InvalidArguments(
            {
                name: [CodedMessage(gettext("This field is required."), "required")]
                for name in missing
            }
        )
    return resolve_callable_kwargs(fn, dict(pool))


def apply_shaping(
    queryset: Any,
    spec: SelectorSpec,
    pool: Mapping[str, Any],
    *,
    annotations: Mapping[str, Any] | None,
    source_label: str,
    fillable: frozenset[str],
) -> Any:
    """``shape_queryset``, with the annotations it applies named by the caller.

    ``shape_queryset`` passes the spec's own. Dispatch passes them with every
    affordance answer the spec declares beside them, built against the model
    the selector returned, so each answer rides in the one ``.annotate()`` call
    and ``extend_queryset`` sees the answers as it sees a declared annotation.
    The public function cannot build them itself: a callable condition is
    answered against the call's registered seeds, which it is not handed.

    ``extend_queryset`` is bound through ``call_keywords`` with ``fillable``,
    the names the selector beside it was bound with, so a read the caller left
    out is the same refusal whichever of the two takes it:
    test_a_read_left_out_is_refused_alike_by_whichever_callable_takes_it.

    ``filter_set`` runs last, after ``extend_queryset``, so filtering composes
    with the shaping and runs before a RETRIEVE collapses to its row; see
    ``_filtered``. The nothing-to-shape guard is one arc to coverage, and its
    ``filter_set`` condition is held by
    TestFilterSet.test_it_alone_refuses_a_return_that_is_not_a_queryset.
    """
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
    """``extend_queryset``'s return, refusing one that is still to be awaited.

    The seat is sync-only and its return is never awaited. The spec refuses an
    ``async def`` one when it is built, and a plain ``def`` handing back a
    coroutine - a lambda calling an ``async def`` - is refused here, where
    it would otherwise stand in for the queryset and come back from dispatch
    as the value of a list. A coroutine is closed first, so it does not linger
    to warn that it was never awaited. Two disjuncts, each held in
    ``tests/selectors/test_utils.py``'s
    ``TestAnExtendQuerysetAnsweringWithAnAwaitable``:
    ``test_an_awaitable_that_is_not_a_coroutine_is_refused`` fails without the
    first and ``test_an_async_generator_is_refused`` without the second, since
    an async generator is not awaitable.
    """
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
    """``queryset`` narrowed by ``filter_set``, from the arguments its filters read.

    Its ``data`` is the pool's value for each name its filters read, which
    ``SelectorSpec`` made reads, so the shape check has already judged them
    and the pool carries exactly the ones the caller sent. Never the whole
    pool, and never a pool entry called ``data``: a transport shaping rows
    itself may hand over a pool with one, and it is a filter's argument only
    under a filter's own name (test_a_pool_s_data_is_not_the_filters_data).

    ``request`` is handed over when the pool carries one - a seed an HTTP
    adapter registers - and the constructor declares it, by the
    declare-to-receive rule of every pool-resolved callable, so a
    request-scoped FilterSet sees the ``self.request`` it would behind
    django-filter's own backend.

    A FilterSet that refuses its data is refused here, as ``InvalidArguments``
    keyed as the FilterSet keys its errors. Reading ``.qs`` without
    ``is_valid()`` would answer the **unfiltered** rows in django-filter's
    default non-strict mode, so a bad value would read as a filter that matched
    everything (test_a_value_the_filterset_refuses_is_refused_rather_than_ignored).
    A range filter's error is keyed by the filter's name, ``price``, where its
    arguments are ``price_min`` and ``price_max``: django-filter validates the
    two as one form field. Each message keeps django-filter's own code, its
    form field's, which reading it as a ``str`` would drop
    (test_a_value_the_filterset_refuses_keeps_django_s_code).

    A value the FilterSet accepts and its filter's integer column cannot hold
    is refused next, before any lookup is built with it; see
    ``_past_their_columns``.
    """
    seen = {"request": pool["request"]} if "request" in pool else {}
    bound = filter_set(
        **resolve_callable_kwargs(filter_set, seen),
        data=_filter_data(filter_set, pool),
        queryset=queryset,
    )
    if not bound.is_valid():
        raise InvalidArguments(
            {name: coded_messages(errors) for name, errors in bound.errors.as_data().items()}
        )
    past = _past_their_columns(bound, queryset)
    if past:
        raise InvalidArguments(past)
    return bound.qs


def _past_their_columns(bound: Any, queryset: Any) -> dict[str, Any]:
    """Each argument carrying a number its filter's integer column cannot hold, and its refusal.

    The driver refuses such a number with ``OverflowError`` as the query
    runs: for an ``in`` or a ``range`` lookup and for any lookup on a foreign
    key's own column (``owner_key``) on every Django, and for any lookup on
    Django 4.2's SQLite, which states no range. Django 5.0 and later answer
    the rest, the exact and comparison lookups on an integer column itself,
    without the query - an exact match or a lower bound past the top with no
    rows, an upper bound past it with every row - and they are refused here
    all the same, so a call has one answer on every Django and backend.
    The 1e50 bound every number filter is held to is not this one, because it
    must hold for a decimal or float column too.

    The refusal is the one a model integer field gives: ``max_value`` or
    ``min_value``, in the words of Django's range validators, read off the
    database the queryset reads. It is keyed at the argument that carried
    the number: a range filter's bound at ``price_min`` or ``price_max``, the
    keys the caller sent, and a CSV filter's element at its index, as the
    shape check keys a number past 1e50.

    The value is the one the FilterSet cleaned, read as the column's own
    lookup reads it, so a fraction is the integer it truncates to. Left to the
    filter, and so to the database: a filter with a ``method``, which decides
    what its value means (test_a_filter_with_a_method_is_left_to_its_method);
    a lookup that does not read its value as the column's, such as
    ``contains`` (test_a_lookup_reading_the_value_as_text_is_left_to_it); a
    path that names no integer column (``_column``); a value no integer column
    reads as a number, such as the row a model choice filter cleans to, or a
    choice filter's empty value and ``null`` choice, which it reads as nothing
    sent and as a null; and an object that is no
    FilterSet, which has no cleaned data to read
    (test_an_object_that_is_no_filterset_is_left_to_the_database).
    """
    refusals: dict[str, Any] = {}
    if not isinstance(bound, import_django_filters().FilterSet):
        return refusals
    for name, filter_obj in bound.filters.items():
        if filter_obj.method is not None:
            continue
        column = _column(queryset.model, filter_obj.field_name)
        bounds = integer_column_range(column, queryset.db)
        # One arc to coverage, a condition each:
        # test_a_decimal_column_takes_a_number_past_any_integer_s (the
        # column) and test_a_lookup_reading_the_value_as_text_is_left_to_it
        # (the lookup). A lookup preparing its value hands it to the column's
        # ``get_prep_value``, which is the conversion the driver then refuses.
        if bounds is None or not getattr(
            column.get_lookup(filter_obj.lookup_expr), "prepare_rhs", False
        ):
            continue
        for key, index, value in _sent(name, filter_obj, bound.form.cleaned_data.get(name)):
            try:
                number = column.get_prep_value(value)
            except (TypeError, ValueError):
                # Not a number of the column's, and so the filter's to read:
                # the row a model choice filter cleans to
                # (test_a_related_row_is_matched_as_its_key), or the empty
                # string a choice filter left out cleans to, which it reads as
                # nothing sent (test_the_date_shapes_narrow_the_rows' ``level``),
                # and its ``null`` choice (test_a_choice_filter_s_null_choice_is_left_to_it).
                continue
            refusal = integer_range_refusal(number, bounds)
            if refusal is None:
                continue
            if index is None:
                refusals[key] = coded_messages([refusal])
            else:
                refusals.setdefault(key, {})[index] = coded_messages([refusal])
    return refusals


def _column(model: Any, path: str) -> Any:
    """The model field a filter's ``field_name`` ends on, or ``None`` where it names none.

    Each part of the path is a field of the model the part before it relates
    to, and ``pk`` is the model's key, as Django reads a lookup's path. A
    foreign key's column holds the key of the row it points at, so the field
    is that key (``owner_key`` in
    test_it_is_refused_at_the_argument_that_sent_it). ``None`` past a field
    that relates to nothing, which is a transform such as ``year``
    (test_a_transform_on_the_filter_s_path_is_left_to_the_lookup), and for a
    name no model declares, such as an annotation
    (test_a_filter_on_an_annotation_is_left_to_the_database).
    """
    opts: Any = model._meta
    column: Any = None
    for part in path.split(LOOKUP_SEP):
        if opts is None:
            return None
        try:
            column = opts.pk if part == "pk" else opts.get_field(part)
        except FieldDoesNotExist:
            return None
        related = column.related_model
        opts = None if related is None else related._meta
    while isinstance(column, ForeignKey):
        column = column.target_field
    return column


def _sent(name: str, filter_obj: Any, value: Any) -> list[tuple[str, int | None, Any]]:
    """Each value a filter's cleaned ``value`` holds: the argument it came in, its index, the value.

    A range filter cleans its two bounds to a ``slice``, each from its own
    argument; a CSV filter cleans to a list, each value at its index. A value
    left out cleans to ``None``, and nothing was sent there.
    """
    if isinstance(value, slice):
        # Not strict: a filter cleaning to a slice with no keys of its own to
        # name has no argument to key a refusal at, and is left to the
        # database.
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
    """The pool's value for each name ``filter_set``'s filters read, as django-filter reads it.

    A CSV filter's list is joined into the comma-separated string its widget
    splits, because the widget takes a list as it is only in later releases:
    at the declared floor, 23.1, it calls ``.split`` on whatever it is handed
    (test_a_csv_filter_s_list_reaches_it_as_the_string_it_splits). An element
    holding a comma is split in two either way, which is the CSV filter's own
    reading.
    """
    names = filter_set_parameters(filter_set).names()
    data = {name: value for name, value in pool.items() if name in names}
    if not data:
        # Nothing sent, or a FilterSet declaring no filters: no filter to ask
        # about, and so no need for django-filter.
        return data
    module = import_django_filters()
    for name, filter_obj in filter_set.base_filters.items():
        value = data.get(name)
        # One arc to coverage, a condition each:
        # test_a_csv_filter_s_list_reaches_it_as_the_string_it_splits (the
        # filter's kind: a multiple choice reads its list as a list) and
        # test_a_csv_filter_sent_a_string_is_handed_it_unchanged (the value).
        if isinstance(filter_obj, module.BaseCSVFilter) and isinstance(value, list):
            data[name] = ",".join(str(element) for element in value)
    return data
