"""``filter_set_parameters`` - a django-filter FilterSet's filters, read as Parameters."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters


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
    ``string``. Every other filter is its scalar: ``boolean``, ``number``, a
    ``date`` or ``date-time`` string, and ``string`` for the rest.

    **Every one is optional**, because a filter narrows a read and never
    stands between a caller and it. ``help`` is the author's ``help_text`` when
    there is one; otherwise it says what the filter matches when the
    argument's name does not (``min_pk`` is ``pk`` with ``gte``), and for a
    bound, which bound of which field it is.

    Two filters that read one key - a range ``joined`` and a filter called
    ``joined_after`` - are refused, as any two Parameters of one name are,
    because django-filter would hand one value to both.

    An object with no ``base_filters`` - a duck-typed stand-in taking
    ``(data, queryset)`` - declares nothing, and is read without django-filter.
    Reading any filter needs the ``[filter]`` extra.
    """
    base_filters: dict[str, Any] = dict(getattr(filter_set, "base_filters", None) or {})
    if not base_filters:
        return Parameters()
    module = _import_django_filters()
    return Parameters(
        tuple(
            parameter
            for name, filter_obj in base_filters.items()
            for parameter in _parameters_for(module, name, filter_obj)
        )
    )


def _import_django_filters() -> Any:
    # Function-local under the optional-dependency exemption: the package never
    # imports django-filter at the top (a ``filter_set`` is applied by duck
    # typing), and only reading a declared filter's kind needs its classes.
    try:
        import django_filters
    except ImportError as exc:
        raise ImportError(
            "Reading a FilterSet's filters requires the `django-filter` package. "
            'Install it with `pip install "django-service-specs[filter]"`.'
        ) from exc
    return django_filters


def _parameters_for(module: Any, name: str, filter_obj: Any) -> Iterator[Parameter]:
    """The one Parameter a filter reads, or one per bound for a range."""
    field_name: str = getattr(filter_obj, "field_name", None) or name
    extra: dict[str, Any] = getattr(filter_obj, "extra", None) or {}
    help_text: Any = extra.get("help_text")
    # A range's widget names the keys it reads; nothing else in django-filter
    # carries ``suffixes``. Read off the field class rather than ``.field``,
    # which would build the form field and, for a related-row filter, its
    # queryset.
    suffixes = getattr(getattr(filter_obj.field_class, "widget", None), "suffixes", None)
    if suffixes:
        type_, format_ = _bound_type(module, filter_obj)
        for suffix in suffixes:
            yield Parameter(
                f"{name}_{suffix}",
                type_,
                format=format_,
                help=str(help_text) if help_text else f"The `{suffix}` bound of `{field_name}`.",
            )
        return
    help_ = _help(name, field_name, filter_obj, help_text)
    offered = _choices(extra)
    # One arc to coverage, a condition each: ``pks`` (a CSV filter) and
    # ``kinds`` (a multiple choice) in
    # test_each_note_filter_reads_as_the_argument_django_filter_reads.
    if isinstance(filter_obj, (module.BaseCSVFilter, module.MultipleChoiceFilter)):
        items, choices = offered or (_scalar(module, filter_obj)[0], None)
        yield Parameter(name, "array", items=items, choices=choices, help=help_)
    elif offered is not None:
        yield Parameter(name, offered[0], choices=offered[1], help=help_)
    else:
        # A related row's filter has a queryset where its ``choices`` would
        # be: its key's type is not known without the database, so it is a
        # string the FilterSet resolves.
        type_, format_ = _scalar(module, filter_obj)
        yield Parameter(name, type_, format=format_, help=help_)


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
        return "number", None
    # A time, a UUID, a duration, text and anything unrecognised: each form
    # field behind them parses a string.
    return "string", None


def _bound_type(module: Any, filter_obj: Any) -> tuple[str, str | None]:
    """The type of each bound of a range filter.

    The date and time ranges subclass ``RangeFilter``, so they are told apart
    first; a numeric range (``RangeFilter`` itself, or the PostgreSQL
    ``NumericRangeFilter``) is a number, and any other suffixed filter a string.
    """
    if isinstance(filter_obj, module.DateTimeFromToRangeFilter):
        return "string", "date-time"
    if isinstance(filter_obj, module.DateFromToRangeFilter):
        return "string", "date"
    if isinstance(filter_obj, module.TimeRangeFilter):
        return "string", None
    if isinstance(filter_obj, (module.RangeFilter, module.NumericRangeFilter)):
        return "number", None
    return "string", None


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
