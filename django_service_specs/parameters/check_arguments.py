from __future__ import annotations

import math
import uuid
from collections.abc import Callable, Mapping
from dataclasses import KW_ONLY, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.files.base import File
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.translation import gettext

from django_service_specs.parameters.coded_message import CodedMessage
from django_service_specs.parameters.expected_type_refusal import expected_type_refusal
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.non_field_errors import NON_FIELD_ERRORS
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.parameters.utils import (
    length_problem,
    parse_number,
    unknown_arguments_policy,
)
from django_service_specs.types.unknown_arguments import UnknownArguments
from django_service_specs.types.unset import UNSET

# Messages are translated where they are raised, never at import: every
# ``django.utils.translation`` function reads settings, and a module that did
# so at import could not be imported before settings are configured. Where a
# stock Django field already has the message, it is spelled exactly as Django
# spells it, so Django's own catalog translates it and a project adds nothing.
# Each is a ``CodedMessage`` carrying the code a DRF field gives the same
# mistake, and test_each_refusal_carries_the_code_a_drf_field_gives_the_same_mistake
# holds each code by the case named for it.

_PYTHON_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": (list, tuple),
    "object": Mapping,
    "file": File,
}
"""What each type arrives as once a transport has decoded it. An ``int`` is a
number, because JSON has one numeric type and ``3`` is a valid number. ``bool``
is handled before this table is read, since it subclasses ``int``. A file is
Django's ``File``, which an upload is and a ``ContentFile`` a Python caller
builds is too."""

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
    partial: bool = False,
) -> dict[str, Any]:
    """The shape check: what a caller can get wrong that the declaration can see."""
    policy = unknown_arguments_policy(unknown_arguments)
    if not isinstance(arguments, Mapping):
        raise InvalidArguments({NON_FIELD_ERRORS: [expected_type_refusal("object")]})
    cleaned, errors = _check_object(parameters, arguments, _Walk(policy, partial=partial))
    if errors:
        raise InvalidArguments(errors)
    return cleaned


@dataclass(frozen=True)
class _Walk:
    """What holds at every level of one call: its unknown-key policy, and whether it is partial."""

    policy: UnknownArguments
    _: KW_ONLY
    partial: bool


def _check_object(
    parameters: Parameters, arguments: Mapping[str, Any], walk: _Walk
) -> tuple[dict[str, Any], dict[Any, Any]]:
    """One level: the cleaned mapping, and every problem found at or below it."""
    cleaned: dict[str, Any] = {}
    errors: dict[Any, Any] = {}
    for param in parameters:
        if param.name not in arguments:
            if param.required and param.default is UNSET and not walk.partial:
                errors[param.name] = [CodedMessage(gettext("This field is required."), "required")]
            continue
        value, detail = _check_value(param, arguments[param.name], walk)
        if detail is None:
            cleaned[param.name] = value
        else:
            errors[param.name] = detail
    if walk.policy is UnknownArguments.REJECT:
        declared = parameters.names()
        for key in arguments:
            if key not in declared:
                errors[key] = [CodedMessage(gettext("Unknown argument."), "unknown")]
    return cleaned, errors


def _check_value(param: Parameter, value: Any, walk: _Walk) -> tuple[Any, Any]:
    """``(cleaned, None)``, or ``(None, detail)`` for a value that is refused."""
    if value is None:
        if param.nullable:
            return None, None
        return None, [CodedMessage(gettext("This field cannot be null."), "null")]
    if param.type != "array":
        return _check_one(
            None if param.type == "any" else param.type,
            value,
            fmt=param.format,
            fields=param.fields,
            choices=param.choices,
            minimum=param.minimum,
            maximum=param.maximum,
            walk=walk,
        )
    if not _is_json_type("array", value):
        return None, [expected_type_refusal("array")]
    problem = length_problem(param, len(value))
    if problem is not None:
        return None, [problem]
    items = param.items
    rows: Parameters | None
    if isinstance(items, Parameters):
        rows, element_type = items, "object"
    else:
        rows, element_type = None, items
    cleaned: list[Any] = []
    errors: dict[int, Any] = {}
    for index, element in enumerate(value):
        if element is None and param.items_nullable:
            cleaned.append(None)
            continue
        checked, detail = _check_one(
            element_type,
            element,
            fmt=param.format,
            fields=rows,
            choices=param.choices,
            minimum=param.minimum,
            maximum=param.maximum,
            walk=walk,
        )
        if detail is None:
            cleaned.append(checked)
        elif rows is not None and isinstance(detail, list):
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
    minimum: float | None = None,
    maximum: float | None = None,
    walk: _Walk,
) -> tuple[Any, Any]:
    """One value against one type: a parameter's own, or an array's element."""
    value = _integral(json_type, _numeric(json_type, value))
    problem = _type_problem(json_type, fmt, value) or _bound_problem(value, minimum, maximum)
    if problem is not None:
        return None, [problem]
    value = _canonical(fmt, value)
    if fields is not None:
        value, errors = _check_object(fields, value, walk)
        if errors:
            return None, errors
    if choices is not None and value not in choices:
        message = gettext("Select a valid choice. %(value)s is not one of the available choices.")
        return None, [CodedMessage(message % {"value": value}, "invalid_choice")]
    return value, None


def _canonical(fmt: str | None, value: Any) -> Any:
    """``value`` in the one spelling its format reads, once the type check has passed it."""
    return str(uuid.UUID(value)) if fmt == "uuid" else value


def _bound_problem(value: Any, minimum: float | None, maximum: float | None) -> CodedMessage | None:
    """The bound a well-typed number is past, or ``None``."""
    if minimum is None and maximum is None:
        return None
    number = Decimal(value) if isinstance(value, str) else value
    if maximum is not None and number > maximum:
        message = gettext("Ensure this value is less than or equal to %(limit_value)s.")
        return CodedMessage(message % {"limit_value": maximum}, "max_value")
    if minimum is not None and number < minimum:
        message = gettext("Ensure this value is greater than or equal to %(limit_value)s.")
        return CodedMessage(message % {"limit_value": minimum}, "min_value")
    return None


def _numeric(json_type: str | None, value: Any) -> Any:
    """``value``, or the number a string spells where an ``integer`` or a ``number`` is declared."""
    if json_type in ("integer", "number") and isinstance(value, str):
        number = parse_number(json_type, value)
        return value if number is None else number
    return value


def _integral(json_type: str | None, value: Any) -> Any:
    """``value``, or the ``int`` an integral float declared an integer stands for."""
    if json_type == "integer" and isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _type_problem(json_type: str | None, fmt: str | None, value: Any) -> CodedMessage | None:
    if fmt == "decimal":
        # A boolean is neither, although Python makes it an int: see _is_json_type.
        if not (_is_json_type("string", value) or _is_json_type("number", value)):
            return expected_type_refusal("decimal")
        try:
            finite = Decimal(value).is_finite()
        except InvalidOperation:
            finite = False
        return None if finite else CodedMessage(gettext("Enter a number."), "invalid")
    if json_type is not None and not _is_json_type(json_type, value):
        return expected_type_refusal(json_type)
    if isinstance(value, float) and not math.isfinite(value):
        return CodedMessage(gettext("Enter a number."), "invalid")
    if fmt is None:
        return None
    if fmt == "uuid":
        return _uuid_problem(value)
    try:
        parsed = _DATE_PARSERS[fmt](value)
    except ValueError:
        parsed = None
    if parsed is not None:
        return None
    return CodedMessage(
        gettext("Enter a valid date/time.")
        if fmt == "date-time"
        else gettext("Enter a valid date."),
        "invalid",
    )


def _uuid_problem(value: str) -> CodedMessage | None:
    """Whether ``value`` spells a UUID, read as ``models.UUIDField.to_python`` reads one."""
    try:
        uuid.UUID(value)
    except ValueError:
        return CodedMessage(gettext("Enter a valid UUID."), "invalid")
    return None


def _is_json_type(json_type: str, value: Any) -> bool:
    if isinstance(value, bool):
        return json_type == "boolean"
    return isinstance(value, _PYTHON_TYPES[json_type])
