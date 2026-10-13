"""The spellings every refusal of arguments shares: a node's own message key, a wrong type, a length.

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

from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext

from django_service_specs.parameters.coded_message import CodedMessage
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.settings import max_array_length

NON_FIELD_ERRORS: Final = "non_field_errors"
"""The key a message about a node itself sits under, beside its fields' messages.

A row that is not an object has no field to hang the message on, so it goes
here inside the row: ``{"books": {1: {"non_field_errors": ["..."]}}}``. It is
Django's and DRF's spelling of the same idea, so a transport rendering either's
errors reads the kernel's without a translation table."""


def expected_type(json_type: str) -> CodedMessage:
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

    Its code is the one DRF gives the same mistake: ``"not_a_list"`` for an
    array, as its ``ListField`` and ``ListSerializer`` both do, and
    ``"invalid"`` for everything else, as each of its scalar fields, its
    ``FileField`` and a nested ``Serializer`` handed something other than a
    mapping do. A free-form ``object`` is ``"invalid"`` too, where DRF's
    ``DictField`` would say ``"not_a_dict"``: one type here stands for both of
    its fields, and the nested serializer is the one a declared object becomes.
    """
    message = {
        "string": gettext("Expected a string."),
        "integer": gettext("Expected an integer."),
        "number": gettext("Expected a number."),
        "boolean": gettext("Expected a boolean."),
        "array": gettext("Expected an array."),
        "object": gettext("Expected an object."),
        "decimal": gettext("Expected a decimal string or a number."),
        "file": gettext("Expected a file."),
    }[json_type]
    # test_each_refusal_carries_the_code_a_drf_field_gives_the_same_mistake[not-a-list]
    # holds the array's code, its [type] case everything else's.
    return CodedMessage(message, "not_a_list" if json_type == "array" else "invalid")


def max_length_in_force(param: Parameter) -> int | None:
    """The most elements the array ``param`` takes: its own ``max_length``, or the setting's.

    One reading for every place that bounds or describes a list - the shape
    check, ``coerce_flat``, the split of a flat value, a ``many`` call's rows
    and the schema - so the bound a client is told is the bound it meets.
    ``None`` where the setting is ``None`` and nothing is declared.

    Raises:
        ImproperlyConfigured: a ``min_length`` past the setting's maximum on a
            parameter that declares no maximum of its own, which no call could
            meet: at the call, and when the parameter's schema is built, so a
            transport listing every schema fails on it too. Found here because
            the setting is read only then, so the declaration cannot be
            refused where it is written.
    """
    if param.max_length is not None:
        return param.max_length
    default = max_array_length()
    # One branch to coverage, each condition held by its own test:
    # test_a_minimum_is_compared_with_no_default_when_the_setting_is_none (the
    # default: without it, a minimum is compared with ``None`` and raises),
    # test_an_array_takes_a_thousand_elements_and_no_more_by_default (the
    # minimum, likewise) and test_a_declared_minimum_is_inclusive (the
    # comparison: without it, every declared minimum is refused).
    if default is not None and param.min_length is not None and param.min_length > default:
        raise ImproperlyConfigured(
            f"Parameter {param.name!r}: min_length {param.min_length} is past the default maximum "
            f"{default} (SERVICE_SPECS_MAX_ARRAY_LENGTH), so no list could meet both; declare "
            "a max_length."
        )
    return default


def length_problem(param: Parameter, count: int) -> CodedMessage | None:
    """The refusal of an array of ``count`` elements, or ``None`` where ``param`` takes that many.

    In DRF's words, its ``ListField`` and ``ListSerializer`` both: no Django
    catalog entry counts a list's elements (``MaxLengthValidator`` counts a
    string's characters), and DRF's catalog translates these wherever DRF is
    installed, which is where a djangorestframework-services caller already
    reads them, and with DRF's codes, ``"max_length"`` and ``"min_length"``.
    """
    most = max_length_in_force(param)
    if most is not None and count > most:
        return CodedMessage(
            gettext("Ensure this field has no more than {max_length} elements.").format(
                max_length=most
            ),
            "max_length",
        )
    if param.min_length is not None and count < param.min_length:
        return CodedMessage(
            gettext("Ensure this field has at least {min_length} elements.").format(
                min_length=param.min_length
            ),
            "min_length",
        )
    return None


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
    ``"5."``, ``"5 .0"`` and ``" 5 "`` are 5, and ``"5.5"`` and ``"1e3"`` are
    no integer. That is looser than pydantic's lax ``int``, which refuses
    ``"5."`` and ``"5 .0"``. A number is Python's ``float``, as Django's
    ``FloatField`` reads it, so ``"1e3"`` is 1000.0 and ``"5."`` is 5.0, as
    pydantic reads them too, and ``"5 .0"`` is none. NaN and the infinities
    parse and are no number, since no JSON caller can send one.

    **Only an ASCII string spells one.** Python's ``int`` and ``float``,
    and so Django's fields, read Arabic-Indic and fullwidth digits and strip
    any Unicode space, which no JSON number is spelled with and pydantic
    refuses; reading them would hand on a number the caller never wrote in
    digits. Stricter than Django's forms there, and only there. A decimal
    string is not read here: the shape check reads it as ``Decimal`` does,
    which takes those digits.

    The caller decides what a ``None`` means: a flat transport refuses it, and
    the shape check refuses the string as the type it is not.
    """
    if not text.isascii():
        # test_a_number_spelled_outside_ascii_spells_none fails without this.
        return None
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
