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
    """A flat source as strings and lists of strings, read by ``parameters``, blanks read as absent.

    A flat source is a query string or a form's fields: Django's ``QueryDict``,
    or any ``MultiValueDict``, where every value is a string and a key may
    repeat. A transport reading one calls this, merges its route's kwargs into
    what comes back, and hands the result to
    [`coerce_flat`][django_service_specs.parameters.coerce_flat.coerce_flat],
    so every transport reading a flat wire reads it by the same rules. Nothing
    is coerced here.

    **A flat source is read by the declaration.** A parameter of type
    ``array`` takes every value its key was sent with, and anything else takes
    the last, as ``QueryDict`` reads a repeated key. **An array of numbers,
    integers, booleans or decimal strings also reads a value holding commas
    as its elements**, ``?ids=1,2`` as ``["1", "2"]`` with the space around a
    part trimmed, because a comma cannot be part of such a value and it is
    the spelling a django-filter CSV filter advertises; repeated keys and
    commas may mix. An empty part (``?ids=1,,2``) is not dropped as a blank
    element is: it is kept, for ``coerce_flat`` to refuse at its index as any
    malformed element is. A string array is split only where its choices
    hold no comma, as an ordering's do, so ``?o=title,-pk`` is
    ``["title", "-pk"]``; otherwise it is never split, since a comma is part
    of a string. **An array is read no further than one element past the
    most it takes** - its ``max_length``, or the
    ``SERVICE_SPECS_MAX_ARRAY_LENGTH`` setting's default - so ``coerce_flat``
    refuses a list over it at its name as a whole, without a million commas
    becoming a million elements first; Django's
    ``DATA_UPLOAD_MAX_NUMBER_FIELDS`` counts keys, and a comma list is one.
    **A blank value is absent unless** ``""`` **is one the parameter can
    take**: a plain string can, and a number, a boolean, a date, a decimal,
    or a string whose choices leave the blank out cannot. A flat wire has no
    other spelling of "left blank", and an empty ``?count=`` or ``?since=``
    from a filter form is not a refusal to count or a malformed date. Each
    blank element of an array is read by the same rule, the whole array
    absent once nothing is left. Django's ``csrfmiddlewaretoken``, the field
    ``{% csrf_token %}`` renders into a form, is dropped: no Django transport
    takes it as an argument. A key ``parameters`` do not declare is kept as
    it is, so the closed argument set in dispatch stays the one place that
    refuses it, under the caller's policy.
    """
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
