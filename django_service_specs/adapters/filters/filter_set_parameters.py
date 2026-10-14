"""``filter_set_parameters`` - a django-filter FilterSet's filters, read as Parameters."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from django_service_specs.adapters.filters.utils import import_django_filters, range_suffixes
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters

_NUMBER_BOUND = 1e50
"""The bound on every decimal a FilterSet reads: django-filter's own.

``NumberFilter.get_max_validator`` returns ``MaxValueValidator(1e50)``, and it
is the only bound django-filter puts on a number. A range's two
``DecimalField`` bounds have none, and nothing bounds a number filter from
below, so either side past it reached the integer field's ``int()`` and built
every digit of the value: ``"1E+999999999"`` held a worker for minutes. Kept a
``float``, as django-filter's is, so the line falls where its validator draws
it. The minimum is the same bound mirrored: the kernel's own, with no
django-filter counterpart, because the cost is the same on either side.
"""


def filter_set_parameters(filter_set: Any) -> Parameters:
    """The arguments a ``FilterSet`` reads, as the Parameters a caller sends.

    This is what lets a filter be a read like any other: the schema describes
    it, the closed argument set admits it, the shape check judges it and each
    transport accepts it, all from the declaration rather than from
    django-filter. ``SelectorSpec`` puts these after its own ``reads``.

    **Named as django-filter reads them**, because a Parameter describes what a
    caller sends and the FilterSet is what receives it. A range filter
    (``RangeFilter``, ``DateFromToRangeFilter`` and the rest) reads one key per
    bound - ``price_min`` and ``price_max``, ``joined_after`` and
    ``joined_before`` - so it is one Parameter per bound, never an object
    called ``price`` that no FilterSet reads. A CSV filter (``BaseInFilter``,
    ``BaseRangeFilter``) reads one key holding several values, and is an array;
    its widget takes a list as it takes ``"1,2"``. A choice filter offers its
    values, flattened out of any group, as ``integer`` when every value is an
    ``int`` and otherwise as the strings Django's ``ChoiceField`` compares; a
    choice set built by a callable, and a related row's key, offer only
    ``string``. Every other filter is its scalar: ``boolean``, a ``date`` or
    ``date-time`` string, and ``string`` for the rest. **A number filter, and
    each bound of a numeric range, is a** ``decimal`` **string**, because its
    form field is a ``DecimalField`` and reads one exactly, where a float read
    on the way loses a key past ``2**53``; a JSON number is still taken. **So
    is each value of a CSV number filter**: an array whose ``format`` and
    bounds describe each element, as its choices would, so a fraction keeps
    every digit it was sent with and ``?pks=1,2`` still splits over HTTP,
    since no decimal holds a comma. **Each decimal is bounded**,
    ``minimum=-1e50`` and ``maximum=1e50``, a CSV filter's values each: the
    line django-filter's number filter draws above, drawn below too and on a
    range's bounds, which it leaves open. A value past it is refused by the
    shape check, at its index in a CSV filter's list, before it reaches the
    database's integer conversion, which builds every digit of
    ``"1E+999999999"``.

    **Every one is optional**, because a filter narrows a read and never
    stands between a caller and it. ``help`` is the author's ``help_text`` when
    there is one; otherwise it says what the filter matches when the
    argument's name does not (``min_pk`` is ``pk`` with ``gte``), and for a
    bound, which bound of which field it is.

    Two filters that read one key - a range ``joined`` and a filter called
    ``joined_after`` - are refused, as any two Parameters of one name are,
    because django-filter would hand one value to both.

    An object whose ``base_filters`` is missing, empty or ``None`` declares
    nothing, and is read without django-filter. A
    [`SelectorSpec`][django_service_specs.specs.selector_spec.SelectorSpec]
    refuses one as its ``filter_set`` unless it is a django-filter
    ``FilterSet`` class, since none of the caller's data would be handed to
    it. Reading any filter needs the ``[filter]`` extra.
    """
    base_filters: dict[str, Any] = dict(getattr(filter_set, "base_filters", None) or {})
    if not base_filters:
        return Parameters()
    module = import_django_filters()
    return Parameters(
        tuple(
            parameter
            for name, filter_obj in base_filters.items()
            for parameter in _parameters_for(module, name, filter_obj)
        )
    )


def _parameters_for(module: Any, name: str, filter_obj: Any) -> Iterator[Parameter]:
    """The one Parameter a filter reads, or one per bound for a range."""
    field_name: str = getattr(filter_obj, "field_name", None) or name
    extra: dict[str, Any] = getattr(filter_obj, "extra", None) or {}
    help_text: Any = extra.get("help_text")
    suffixes = range_suffixes(filter_obj)
    if suffixes:
        type_, format_ = _bound_type(module, filter_obj)
        minimum, maximum = _bounds(format_)
        for suffix in suffixes:
            yield Parameter(
                f"{name}_{suffix}",
                type_,
                format=format_,
                help=str(help_text) if help_text else f"The `{suffix}` bound of `{field_name}`.",
                minimum=minimum,
                maximum=maximum,
            )
        return
    help_ = _help(name, field_name, filter_obj, help_text)
    offered = _choices(extra)
    # One arc to coverage, a condition each: ``pks`` (a CSV filter) and
    # ``kinds`` (a multiple choice) in
    # test_each_note_filter_reads_as_the_argument_django_filter_reads.
    if isinstance(filter_obj, (module.BaseCSVFilter, module.MultipleChoiceFilter)):
        if offered is not None:
            yield Parameter(name, "array", items=offered[0], choices=offered[1], help=help_)
            return
        # Each element read as the filter's scalar would be: a number filter's
        # as a bounded decimal, the format and the bounds describing the
        # element, as an array's choices do.
        items, format_ = _element(module, filter_obj)
        minimum, maximum = _bounds(format_)
        yield Parameter(
            name,
            "array",
            items=items,
            format=format_,
            help=help_,
            minimum=minimum,
            maximum=maximum,
        )
    elif offered is not None:
        yield Parameter(name, offered[0], choices=offered[1], help=help_)
    else:
        # A related row's filter has a queryset where its ``choices`` would
        # be: its key's type is not known without the database, so it is a
        # string the FilterSet resolves.
        type_, format_ = _scalar(module, filter_obj)
        minimum, maximum = _bounds(format_)
        yield Parameter(name, type_, format=format_, help=help_, minimum=minimum, maximum=maximum)


def _help(name: str, field_name: str, filter_obj: Any, help_text: Any) -> str | None:
    """What the filter matches, when the argument's own name does not say.

    An author's ``help_text`` wins: they know what the filter is for, and this
    only knows its shape. Silent where the name already carries it - a filter
    called ``title`` matching ``title`` exactly has nothing to add.
    """
    if help_text:
        return str(help_text)
    lookup: str = getattr(filter_obj, "lookup_expr", None) or "exact"
    if field_name == name and lookup == "exact":
        return None
    return f"Matches `{field_name}` with the `{lookup}` lookup."


def _scalar(module: Any, filter_obj: Any) -> tuple[str, str | None]:
    """The JSON type and format of one value a filter reads; subclasses before bases."""
    if isinstance(filter_obj, module.BooleanFilter):
        return "boolean", None
    if isinstance(filter_obj, module.DateTimeFilter):
        return "string", "date-time"
    if isinstance(filter_obj, module.DateFilter):
        return "string", "date"
    if isinstance(filter_obj, module.NumberFilter):
        # Its form field is a ``DecimalField``, which reads a string exactly.
        # Declared a ``number``, a string argument was read as a float on the
        # way, and a key past ``2**53`` matched its neighbour's row; a decimal
        # stays the string it was sent, and still takes a JSON number.
        return "string", "decimal"
    # A time, a UUID, a duration, text and anything unrecognised: each form
    # field behind them parses a string.
    return "string", None


def _element(module: Any, filter_obj: Any) -> tuple[str, str | None]:
    """The JSON type and format of each value a CSV filter reads.

    A number filter's element is its scalar's ``decimal`` string, which over
    HTTP splits ``?pks=1,2`` as a number's would, since no decimal holds a
    comma, and is handed on exactly: a key past ``2**53`` matches its own
    row, and a fraction keeps every digit it was sent with. Any other element
    keeps its scalar's type and no format: an element takes none but a
    decimal's, so a date's is left to the FilterSet's own field. Held by
    test_each_note_filter_reads_as_the_argument_django_filter_reads (``pks``,
    the decimal kept) and test_a_csv_filter_of_dates_reads_strings_with_no_format
    (a date's dropped, which ``Parameter`` would refuse on an array).
    """
    type_, format_ = _scalar(module, filter_obj)
    return type_, (format_ if format_ == "decimal" else None)


def _bound_type(module: Any, filter_obj: Any) -> tuple[str, str | None]:
    """The type of each bound of a range filter.

    The date and time ranges subclass ``RangeFilter``, so they are told apart
    first; a numeric range (``RangeFilter`` itself, or the PostgreSQL
    ``NumericRangeFilter``) is a decimal, for the reason a number filter is -
    each bound's form field is a ``DecimalField`` - and any other suffixed
    filter a string.
    """
    if isinstance(filter_obj, module.DateTimeFromToRangeFilter):
        return "string", "date-time"
    if isinstance(filter_obj, module.DateFromToRangeFilter):
        return "string", "date"
    if isinstance(filter_obj, module.TimeRangeFilter):
        return "string", None
    if isinstance(filter_obj, (module.RangeFilter, module.NumericRangeFilter)):
        return "string", "decimal"
    return "string", None


def _bounds(format_: str | None) -> tuple[float | None, float | None]:
    """``minimum`` and ``maximum`` for a decimal, and nothing for any other value.

    A decimal is what a number filter and a numeric range's bounds read, and
    nothing else here is one, so the format is what names them.
    """
    if format_ == "decimal":
        return -_NUMBER_BOUND, _NUMBER_BOUND
    return None, None


def _choices(extra: dict[str, Any]) -> tuple[str, tuple[Any, ...]] | None:
    """The type and values a choice filter offers, or ``None`` when it offers none here.

    ``None`` for a callable or absent ``choices``: they are resolved when the
    form field is built, which reading the declaration does not do. Integers
    stay integers, so ``?level=1`` and a JSON ``1`` both arrive; any other set
    is offered as the strings Django's ``ChoiceField`` compares the argument
    against, ``True`` included. A value is never labelled here.
    """
    choices: Any = extra.get("choices")
    if not choices or callable(choices):
        return None
    values = tuple(_values(choices))
    if all(type(value) is int for value in values):
        return "integer", values
    return "string", tuple(str(value) for value in values)


def _values(choices: Any) -> Iterator[Any]:
    """Each value of a choices list: ``(value, label)``, a named group, or a mapping's key.

    A bare value is what iterating a ``{value: label}`` mapping yields, which
    Django takes as choices from 5.0.
    """
    for choice in choices:
        if not isinstance(choice, (tuple, list)):
            yield choice
        elif isinstance(choice[1], (tuple, list)):
            yield from _values(choice[1])
        else:
            yield choice[0]
