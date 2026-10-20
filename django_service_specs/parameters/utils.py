"""The spellings every refusal of arguments shares, and the readings behind them.

[`InvalidArguments`][django_service_specs.parameters.invalid_arguments.InvalidArguments]
documents the tree these go into. They live here so that everything producing
one - the shape check, ``coerce_flat``, a relation write re-rooting a row's
refusal, an adapter's Validator - spells them the same way, rather than each
its own and a transport learning several. The one reading of an
unknown-arguments policy sits here too, shared by the shape check and its
schema.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable

from django.core.exceptions import ValidationError
from django.utils.translation import gettext

from django_service_specs.parameters.coded_message import CodedMessage
from django_service_specs.parameters.max_length_in_force import max_length_in_force
from django_service_specs.parameters.parameters import Parameter
from django_service_specs.types.unknown_arguments import UnknownArguments


def coded_messages(errors: Iterable[ValidationError]) -> list[CodedMessage]:
    """Every message Django's ``errors`` carry, in Django's words and with Django's code.

    For a step that hands on a ``ValidationError`` Django or a library over it
    raised - a form's errors, a FilterSet's, a model's uniqueness checks, a
    dataclass's ``__post_init__`` - where reading each message as a ``str``
    would drop its code. Rendered exactly as iterating the error renders it,
    ``message % params`` where there are params, so the words are unchanged.
    One raised with no code says ``"invalid"``, as DRF's ``get_error_detail``
    defaults one. An error built from a dict is read field by field, in its
    own order, as its ``messages`` flattens it.

    Django's codes are Django's, which are not always DRF's: a ``unique_together``
    collision says ``"unique_together"`` where a DRF serializer's validator
    says ``"unique"``.
    """
    return [
        CodedMessage(_rendered(leaf), leaf.code or "invalid")
        for error in errors
        for leaf in _leaves(error)
    ]


def _leaves(error: ValidationError) -> list[ValidationError]:
    """The one-message errors ``error`` holds: its list, or each field's list in turn."""
    if hasattr(error, "error_dict"):
        # test_a_post_init_refusal_keeps_django_s_code_or_says_invalid[by-field]
        # fails without this: a dict-built error has no ``error_list``.
        return [leaf for field in error.error_dict.values() for leaf in field]
    return error.error_list


def _rendered(leaf: ValidationError) -> str:
    """A one-message error's words, as ``ValidationError.__iter__`` renders them."""
    message = leaf.message
    if leaf.params:
        message %= leaf.params
    return str(message)


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
    ``"5."`` and ``"5 .0"``. A number is any string Python's ``float`` reads,
    as Django's ``FloatField`` reads it, so ``"1e3"`` and ``"5."`` are numbers,
    as pydantic reads them too, and ``"5 .0"`` is none. NaN and the infinities
    parse and are no number, since no JSON caller can send one.

    **A number spelling an integer is that exact** ``int``, and a ``float``
    only where a point or an exponent is spelled: what a JSON decoder makes
    of the same literal, so ``"3"`` reaches the Validator as the JSON ``3``
    does. Through ``float`` alone, every integer past 2**53 was rounded to a
    neighbour, and a key sent for a ``number`` named the neighbour's row
    (test_a_number_spelling_an_integer_is_that_exact_int). The ``float``
    reading still decides what is a number. Digits alone that ``int`` refuses
    - past the 4300 digits it reads from Python 3.10.7 on, which zeros in
    front can reach while ``float`` still reads a finite value - spell no
    number, rather than a ``float`` neighbour, as they spell no integer; a
    Python with no limit reads them exactly. A fraction past a ``float``'s
    precision is rounded, as a JSON decoder rounds it: a value that must be
    exact is a ``decimal``.

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
    if not math.isfinite(number):
        return None
    try:
        # test_a_number_spelling_an_integer_is_that_exact_int fails without this.
        return int(text)
    except ValueError:
        # Spelled with neither a point nor an exponent, the digits are an
        # integer, and one ``int`` refuses is past its digit limit: no number
        # at all, never the neighbour ``float`` rounds it to
        # (test_an_integer_literal_past_int_s_digit_limit_is_refused_never_rounded).
        return number if any(mark in text for mark in ".eE") else None


def unknown_arguments_policy(value: UnknownArguments | str) -> UnknownArguments:
    """``value`` as a policy: a member, or its plain value, refusing what is not a policy.

    Normalized, so the policy's plain value works and a misspelt one raises
    ``ValueError`` rather than quietly falling through to one policy or the
    other. ``PASSTHROUGH`` is a valid member and not a policy, so it is
    refused here too: both readers test only ``is REJECT`` after this, and a
    member let through would run as ``IGNORE`` with nothing failing.
    """
    policy = UnknownArguments(value)
    if policy is UnknownArguments.PASSTHROUGH:
        raise ValueError(
            "UnknownArguments.PASSTHROUGH is refused: it is kept as a name and is not a "
            "policy, since an argument no parameter declares never reaches a callable. "
            "Pass REJECT, or IGNORE to drop the undeclared argument."
        )
    return policy
