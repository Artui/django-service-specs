"""``coerce_flat`` - argv or a query string, read as a JSON caller would have sent it."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from django.utils.translation import gettext

from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameters import Parameters

# Messages are translated where they are raised, never at import, and spelled as
# a stock Django field spells them where one has the message, so Django's own
# catalog translates them; see check_arguments.

_BOOLEANS = {"true": True, "1": True, "false": False, "0": False}
"""The only spellings a boolean has, matched case-insensitively.

The libraries disagree about every other one - a Django ``BooleanField`` reads
``"no"``, ``"off"`` and ``"n"`` as true, because any other non-empty string is
- so a refusal is the one answer they all share, and the only one that cannot
set a flag the caller meant to clear."""


def coerce_flat(parameters: Parameters, raw: Mapping[str, Any]) -> dict[str, Any]:
    """Flat strings to the JSON-like primitives a typed caller would have sent.

    Every flat-string transport - argv, a query string - needs this, and needs
    it to agree, so it is the kernel's rather than each transport's: validation
    libraries read strings differently from one another, and after this every
    Validator sees an argv call exactly as it would see typed JSON. It is
    directed by the declaration: an ``integer`` or a ``number`` is parsed, a
    ``boolean`` is parsed from exactly four spellings, and everything else is
    left as the string it arrived as. **A decimal, a date-time and a date stay
    strings**, for the Validator to decode, exactly as they would arrive off a
    JSON wire.

    - An array's elements are each coerced by its ``items`` type, and a single
      value becomes a one-element list, since a flat transport sends a
      one-element list as a bare value. ``None`` is not wrapped: an option
      argparse never received is absent, not a list holding a null.
    - **A parameter with nested Parameters is refused by name**: an object, or
      an array of objects, has no flat spelling, and passing its strings through
      would leave the refusal to a type error that does not say why.
    - A key the parameters do not declare passes through untouched, so the
      closed argument set in ``check_arguments`` stays the one place that
      refuses it, under the caller's policy.
    - A value that is not a string passes through untouched: it has already
      been decoded by someone, and this does not second-guess them.

    Raises:
        InvalidArguments: every refusal at once, a parameter's at its name and
            an array element's at its index: ``{"ids": {1: ["..."]}}``.
    """
    coerced: dict[str, Any] = {}
    errors: dict[Any, Any] = {}
    for key, value in raw.items():
        param = parameters.get(key)
        if param is None:
            coerced[key] = value
            continue
        if param.nested is not None:
            errors[key] = [
                gettext("This argument has nested parameters, which a flat transport cannot send.")
            ]
            continue
        # The second condition is held by test_none_is_not_wrapped_into_an_array.
        if param.type != "array" or value is None:
            value, problem = _coerce_one(param.type, value)
            if problem is None:
                coerced[key] = value
            else:
                errors[key] = [problem]
            continue
        # ``nested`` is None, so ``items`` is a type name or undeclared; an
        # undeclared element is left as the string it arrived as.
        item_type = param.items if isinstance(param.items, str) else "string"
        elements = list(value) if isinstance(value, list | tuple) else [value]
        found: dict[int, list[str]] = {}
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


def _coerce_one(json_type: str, value: Any) -> tuple[Any, str | None]:
    """``(value, None)``, or ``(None, message)`` for a string that does not parse."""
    if not isinstance(value, str):
        return value, None
    if json_type == "integer":
        try:
            return int(value), None
        except ValueError:
            return None, gettext("Enter a whole number.")
    if json_type == "number":
        try:
            number = float(value)
        except ValueError:
            number = math.nan
        # NaN and the infinities parse, and no JSON caller can send one.
        return (number, None) if math.isfinite(number) else (None, gettext("Enter a number."))
    if json_type == "boolean":
        lowered = value.lower()
        if lowered in _BOOLEANS:
            return _BOOLEANS[lowered], None
        return None, gettext("Enter true, false, 1 or 0.")
    return value, None
