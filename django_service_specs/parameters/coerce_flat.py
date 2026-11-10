from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from django.utils.translation import gettext

from django_service_specs.parameters.coded_message import CodedMessage
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.parameters.utils import length_problem, parse_number

# Messages are translated where they are raised, never at import, and spelled as
# a stock Django field spells them where one has the message, so Django's own
# catalog translates them; see check_arguments. Each carries the code a DRF
# field gives the same mistake, held by
# test_each_refusal_carries_the_code_a_drf_field_gives_the_same_mistake: every
# one here is ``"invalid"``, a nested serializer's code for a string included.

_BOOLEANS = {"true": True, "1": True, "false": False, "0": False}
"""The only spellings a boolean has, matched case-insensitively.

The libraries disagree about every other one - a Django ``BooleanField`` reads
``"no"``, ``"off"`` and ``"n"`` as true, because any other non-empty string is
- so a refusal is the one answer they all share, and the only one that cannot
set a flag the caller meant to clear."""


def coerce_flat(parameters: Parameters, raw: Mapping[str, Any]) -> dict[str, Any]:
    """Flat strings to the JSON-like primitives a typed caller would have sent."""
    coerced: dict[str, Any] = {}
    errors: dict[Any, Any] = {}
    for key, value in raw.items():
        param = parameters.get(key)
        if param is None:
            coerced[key] = value
            continue
        if param.nested is not None:
            message = gettext(
                "This argument has nested parameters, which a flat transport cannot send."
            )
            errors[key] = [CodedMessage(message, "invalid")]
            continue
        if param.type != "array" or value is None:
            value, problem = _coerce_one(param.type, value)
            if problem is None:
                coerced[key] = value
            else:
                errors[key] = [problem]
            continue
        item_type = param.items if isinstance(param.items, str) else "any"
        elements = list(value) if isinstance(value, list | tuple) else [value]
        problem = length_problem(param, len(elements))
        if problem is not None:
            errors[key] = [problem]
            continue
        found: dict[int, list[CodedMessage]] = {}
        for index, element in enumerate(elements):
            elements[index], problem = _coerce_one(item_type, element)
            if problem is not None:
                found[index] = [problem]
        if found:
            errors[key] = found
        else:
            coerced[key] = elements
    if errors:
        raise InvalidArguments(errors)
    return coerced


def _coerce_one(json_type: str, value: Any) -> tuple[Any, CodedMessage | None]:
    """``(value, None)``, or ``(None, message)`` for a string that does not parse."""
    if json_type == "string" and isinstance(value, uuid.UUID):
        return str(value), None
    if not isinstance(value, str):
        return value, None
    if json_type in ("integer", "number"):
        number = parse_number(json_type, value)
        if number is not None:
            return number, None
        return None, CodedMessage(
            gettext("Enter a whole number.")
            if json_type == "integer"
            else gettext("Enter a number."),
            "invalid",
        )
    if json_type == "boolean":
        lowered = value.lower()
        if lowered in _BOOLEANS:
            return _BOOLEANS[lowered], None
        return None, CodedMessage(gettext("Enter true, false, 1 or 0."), "invalid")
    return value, None
