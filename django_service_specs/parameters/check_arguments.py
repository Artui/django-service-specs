"""``check_arguments`` - the shape check and the closed argument set, at every level."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from django.utils.dateparse import parse_date, parse_datetime
from django.utils.translation import gettext

from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.parameters.utils import NON_FIELD_ERRORS, expected_type
from django_service_specs.types.unset import UNSET
from django_service_specs.validation.unknown_arguments import UnknownArguments

# Messages are translated where they are raised, never at import: every
# ``django.utils.translation`` function reads settings, and a module that did
# so at import could not be imported before settings are configured. Where a
# stock Django field already has the message, it is spelled exactly as Django
# spells it, so Django's own catalog translates it and a project adds nothing.

_PYTHON_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": (list, tuple),
    "object": Mapping,
}
"""What each JSON type arrives as once a transport has decoded it. An ``int`` is a
number, because JSON has one numeric type and ``3`` is a valid number. ``bool``
is handled before this table is read, since it subclasses ``int``."""

_DATE_PARSERS: dict[str, Callable[[str], object]] = {
    "date-time": parse_datetime,
    "date": parse_date,
}
"""Django's own parsers, because a Django Validator decodes the string with the
same ones, and a check that parsed differently would refuse what the worker
accepts or pass what it refuses."""


def check_arguments(
    parameters: Parameters,
    arguments: Mapping[str, Any],
    *,
    unknown_arguments: UnknownArguments = UnknownArguments.REJECT,
) -> dict[str, Any]:
    """The shape check: what a caller can get wrong that the declaration can see.

    Presence, JSON type, format, choices and nullability, at every level of
    nesting, with no query. It is what runs at enqueue time and in front of an
    untrusted caller's Validator, so a malformed call is refused before it costs
    a row lookup, and **it is no stricter than the libraries behind it**: a
    decimal accepts a JSON number as well as a string, because every decimal
    validator does, and a check stricter than the worker refuses what would
    have run.

    - A required parameter with a declared default is not refused when absent,
      because the Validator will supply the default. The default is not
      applied here: whether an omitted argument arrives as its default is the
      validating library's behaviour, not the shape check's.
    - ``bool`` is neither an ``integer`` nor a ``number``, although Python
      makes it an ``int``: a JSON ``true`` sent for a count is a caller's
      mistake, not the number one.
    - NaN and the infinities are refused wherever the declaration reaches.
      JSON has no spelling for either, so they are outside the ``number``
      type, and this is a type rule rather than a stricter check - although
      pydantic's ``float``, alone among the validators behind it, takes one.
    - ``choices`` constrain the value, and an array's choices constrain each of
      its elements, since an array is never one of a list of scalars.
    - An ``object`` with no ``fields`` is free-form: its type is checked and
      its contents are not, because nothing is declared inside it to check
      against. An array with no ``items`` takes any element, and each is
      still one of the array's values: its choices and the finiteness rule
      reach it, while an object element is not walked.

    **The closed argument set applies at every level**, inside each row and
    each nested object as well as at the top. Closed only at the top, an
    unknown key in a row would reach the row's constructor and come back as a
    ``TypeError`` naming no row. ``REJECT`` refuses the key where it appeared;
    ``IGNORE`` drops it from the returned copy.

    Returns a cleaned copy and never modifies ``arguments``. The containers it
    walks are new - the top-level mapping, each declared object, each array -
    while a value it does not look inside, such as a free-form object, is
    passed through as the caller's.

    Raises:
        InvalidArguments: carrying **every** problem found as one tree
            addressed by path, rather than the first; the tree's shape is
            documented on ``InvalidArguments``.
    """
    # Normalized, so the policy's plain value works and a misspelt one raises
    # here rather than quietly falling through to one policy or the other.
    policy = UnknownArguments(unknown_arguments)
    if not isinstance(arguments, Mapping):
        # A JSON-RPC caller controls the whole ``arguments`` value, so a list
        # there is a caller's mistake to refuse, not a crash to raise.
        raise InvalidArguments({NON_FIELD_ERRORS: [expected_type("object")]})
    cleaned, errors = _check_object(parameters, arguments, policy)
    if errors:
        raise InvalidArguments(errors)
    return cleaned


def _check_object(
    parameters: Parameters, arguments: Mapping[str, Any], policy: UnknownArguments
) -> tuple[dict[str, Any], dict[Any, Any]]:
    """One level: the cleaned mapping, and every problem found at or below it."""
    cleaned: dict[str, Any] = {}
    errors: dict[Any, Any] = {}
    for param in parameters:
        if param.name not in arguments:
            # One branch to coverage, so each condition is held by its own test:
            # test_an_optional_parameter_may_be_absent_and_stays_absent and
            # test_a_required_parameter_with_a_default_is_not_refused_when_absent.
            if param.required and param.default is UNSET:
                errors[param.name] = [gettext("This field is required.")]
            continue
        value, detail = _check_value(param, arguments[param.name], policy)
        if detail is None:
            cleaned[param.name] = value
        else:
            errors[param.name] = detail
    # Under IGNORE there is nothing to do: ``cleaned`` only ever receives a
    # declared name, so an undeclared one is dropped by never being copied.
    if policy is UnknownArguments.REJECT:
        declared = parameters.names()
        for key in arguments:
            if key not in declared:
                errors[key] = [gettext("Unknown argument.")]
    return cleaned, errors


def _check_value(param: Parameter, value: Any, policy: UnknownArguments) -> tuple[Any, Any]:
    """``(cleaned, None)``, or ``(None, detail)`` for a value that is refused."""
    if value is None:
        return None, (None if param.nullable else [gettext("This field cannot be null.")])
    if param.type != "array":
        return _check_one(
            param.type,
            value,
            fmt=param.format,
            fields=param.fields,
            choices=param.choices,
            policy=policy,
        )
    if not _is_json_type("array", value):
        return None, [expected_type("array")]
    items = param.items
    rows: Parameters | None
    if isinstance(items, Parameters):
        rows, element_type = items, "object"
    else:
        rows, element_type = None, items
    cleaned: list[Any] = []
    errors: dict[int, Any] = {}
    for index, element in enumerate(value):
        # A gap the declaration allows, as ``list[int | None]`` holds one: kept at
        # its index and read against neither the element's type nor its choices,
        # as a nullable parameter's own null is not. One branch to coverage: the
        # first condition is held by
        # test_a_null_element_is_kept_where_the_element_is_nullable (its ``3``),
        # the second by
        # test_a_flat_array_checks_each_element_and_addresses_only_the_failures.
        if element is None and param.items_nullable:
            cleaned.append(None)
            continue
        checked, detail = _check_one(
            element_type,
            element,
            fields=rows,
            choices=param.choices,
            policy=policy,
        )
        if detail is None:
            cleaned.append(checked)
        elif rows is not None and isinstance(detail, list):
            # A message about the row itself - it is not an object at all - goes
            # under non_field_errors inside the row, where a field of that row
            # would otherwise sit, so a transport reads every row the same way.
            # One branch to coverage: the first condition is held by
            # test_a_flat_array_checks_each_element_and_addresses_only_the_failures,
            # the second by test_rows_are_addressed_by_int_index_and_only_the_failing_ones.
            errors[index] = {NON_FIELD_ERRORS: detail}
        else:
            errors[index] = detail
    return (None, errors) if errors else (cleaned, None)


def _check_one(
    json_type: str | None,
    value: Any,
    *,
    fmt: str | None = None,
    fields: Parameters | None = None,
    choices: tuple[Any, ...] | None = None,
    policy: UnknownArguments,
) -> tuple[Any, Any]:
    """One value against one type: a parameter's own, or an array's element.

    ``json_type`` is ``None`` for the element of an array that declares no
    ``items``, which accepts anything.
    """
    problem = _type_problem(json_type, fmt, value)
    if problem is not None:
        return None, [problem]
    if fields is not None:
        value, errors = _check_object(fields, value, policy)
        if errors:
            return None, errors
    if choices is not None and value not in choices:
        return None, [
            gettext("Select a valid choice. %(value)s is not one of the available choices.")
            % {"value": value}
        ]
    return value, None


def _type_problem(json_type: str | None, fmt: str | None, value: Any) -> str | None:
    if fmt == "decimal":
        # A boolean is neither, although Python makes it an int: see _is_json_type.
        if not (_is_json_type("string", value) or _is_json_type("number", value)):
            return expected_type("decimal")
        try:
            finite = Decimal(value).is_finite()
        except InvalidOperation:
            finite = False
        # NaN and the infinities parse, and every decimal validator refuses them.
        return None if finite else gettext("Enter a number.")
    # The first condition is held by test_an_array_with_no_items_accepts_any_element.
    if json_type is not None and not _is_json_type(json_type, value):
        return expected_type(json_type)
    # No JSON value is NaN or an infinity, and neither HTTP reading hands one
    # on by name: ``coerce_flat`` refuses ``"nan"``, a JSON body the constants.
    # A decoder still makes one from an overflowing literal - Python's reads
    # ``1e400`` as infinity - and a Python caller can pass one. Having no JSON
    # spelling puts it outside the number type, so this is a type rule rather
    # than a check stricter than the libraries: every transport refuses it at
    # its own address, in the words Django's number fields use, wherever the
    # declaration reaches. A free-form object's contents are not walked, so
    # one inside is its Validator's. One branch to coverage: the type
    # condition is held by test_accepts_a_value_of_its_json_type[string-], the
    # finiteness one by test_accepts_a_value_of_its_json_type[number-2.5].
    if isinstance(value, float) and not math.isfinite(value):
        return gettext("Enter a number.")
    if fmt is None:
        return None
    try:
        parsed = _DATE_PARSERS[fmt](value)
    except ValueError:
        # Well-formed but impossible, such as the thirtieth of February: Django
        # raises for that where it returns None for a malformed string, and to
        # the caller both are the same mistake.
        parsed = None
    if parsed is not None:
        return None
    return (
        gettext("Enter a valid date/time.")
        if fmt == "date-time"
        else gettext("Enter a valid date.")
    )


def _is_json_type(json_type: str, value: Any) -> bool:
    if isinstance(value, bool):
        return json_type == "boolean"
    return isinstance(value, _PYTHON_TYPES[json_type])
