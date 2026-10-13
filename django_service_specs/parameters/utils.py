"""The spellings every refusal of arguments shares: a node's own message key, and a wrong type.

[`InvalidArguments`][django_service_specs.parameters.invalid_arguments.InvalidArguments]
documents the tree these go into. They live here so that everything producing
one - the shape check, ``coerce_flat``, a relation write re-rooting a row's
refusal, an adapter's Validator - spells them the same way, rather than each
its own and a transport learning several.
"""

from __future__ import annotations

import math
import re
from typing import Final

from django.utils.translation import gettext

NON_FIELD_ERRORS: Final = "non_field_errors"
"""The key a message about a node itself sits under, beside its fields' messages.

A row that is not an object has no field to hang the message on, so it goes
here inside the row: ``{"books": {1: {"non_field_errors": ["..."]}}}``. It is
Django's and DRF's spelling of the same idea, so a transport rendering either's
errors reads the kernel's without a translation table."""


def expected_type(json_type: str) -> str:
    """The refusal of a value that is not ``json_type``, as one sentence a translator sees whole.

    ``"decimal"`` and ``"file"`` are the two keys that are not JSON types: the
    format arrives as a string or a number, so its refusal names both, and a
    file is a parameter's type that no JSON value is.

    One sentence per type rather than ``"Expected %(type)s"``, because an
    interpolated JSON type name would reach a translated sentence
    untranslated. The shape check and the Validators the adapters build share
    this one table, so a caller reads the same refusal whichever of them
    answered. Built on each call, because a translation looked up at import
    time needs configured settings before the package can be imported at all.
    """
    return {
        "string": gettext("Expected a string."),
        "integer": gettext("Expected an integer."),
        "number": gettext("Expected a number."),
        "boolean": gettext("Expected a boolean."),
        "array": gettext("Expected an array."),
        "object": gettext("Expected an object."),
        "decimal": gettext("Expected a decimal string or a number."),
        "file": gettext("Expected a file."),
    }[json_type]


_INTEGRAL_DECIMAL = re.compile(r"\.0*\s*$")
"""A decimal point with nothing after it but zeros and space, stripped before ``int``.

It is Django's own expression: ``forms.IntegerField`` strips exactly this, and
DRF's ``IntegerField`` does too, so ``"5.0"`` and ``"5."`` are 5 to both while
``"5.5"`` is still refused. A reading stricter than the fields behind it would
refuse a value the worker reads as a whole number."""


def parse_number(json_type: str, text: str) -> int | float | None:
    """The number ``text`` spells for an ``integer`` or a ``number``, or ``None`` if it spells none.

    The one reading of a numeric string, shared by ``coerce_flat``, which reads
    every flat transport's strings, and the shape check, which reads a string
    a JSON caller sent for a number. One function, so the two accept exactly
    the same strings and a query string and a JSON body carrying the same
    ``"3"`` reach the Validator as the same 3.

    An integer is read as Django's ``IntegerField`` reads one: ``"5.0"``,
    ``"5."`` and ``" 5 "`` are 5, and ``"5.5"`` and ``"1e3"`` are no integer.
    A number is Python's ``float``, as Django's ``FloatField`` reads it, so
    ``"1e3"`` is 1000.0. NaN and the infinities parse and are no number, since
    no JSON caller can send one. The caller decides what a ``None`` means: a
    flat transport refuses it, and the shape check refuses the string as the
    type it is not.
    """
    if json_type == "integer":
        try:
            return int(_INTEGRAL_DECIMAL.sub("", text))
        except ValueError:
            return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None
