from __future__ import annotations

from typing import Any

from django.utils.datastructures import MultiValueDict

from django_service_specs.parameters.max_length_in_force import max_length_in_force
from django_service_specs.parameters.parameters import Parameter, Parameters

_CSRF_FIELD = "csrfmiddlewaretoken"
"""The field ``{% csrf_token %}`` renders into a form: Django's, and never an argument."""

_COMMA_SEPARABLE = ("number", "integer", "boolean")
"""The element types a comma can never be part of, so ``?ids=1,2`` is two elements, not one.

A string can hold a comma, so a string array takes a value whole, unless its
format or its choices say otherwise: a decimal string never holds one, and
nor does a value its comma-free choices list. See ``_splits``."""


def flat_arguments(parameters: Parameters, source: MultiValueDict) -> dict[str, Any]:
    """A flat source of strings and lists of strings; blanks are read as absent."""
    raw: dict[str, Any] = {}
    for key in source:
        if key == _CSRF_FIELD:
            continue
        param = parameters.get(key)
        if param is not None and param.type == "array":
            keep = _takes_blank(param.items, param, fmt=param.format)
            split = _splits(param)
            most = max_length_in_force(param)
            values: list[str] = []
            for value in source.getlist(key):
                if most is not None and len(values) > most:
                    break
                if value == "" and not keep:
                    continue
                if split:
                    room = -1 if most is None else most - len(values)
                    values.extend(part.strip() for part in value.split(",", room))
                else:
                    values.append(value)
            if values:
                raw[key] = values
            continue
        value = source[key]
        if (
            value == ""
            and param is not None
            and not _takes_blank(param.type, param, fmt=param.format)
        ):
            continue
        raw[key] = value
    return raw


def _splits(param: Parameter) -> bool:
    """Whether a comma in one of the array's values separates elements, so ``?o=a,-b`` is two."""
    if param.items in _COMMA_SEPARABLE or param.format == "decimal":
        return True
    return (
        param.items == "string"
        and param.choices is not None
        and not any("," in str(choice) for choice in param.choices)
    )


def _takes_blank(json_type: object, param: Parameter, *, fmt: str | None = None) -> bool:
    """Whether a blank is a value of ``json_type`` under ``param``, so it is kept, not absent."""
    return (
        (json_type is None or json_type in ("string", "any"))
        and fmt is None
        and (param.choices is None or "" in param.choices)
    )
