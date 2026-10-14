"""The spellings every refusal of arguments shares: a node's own message key, a wrong type, a length.

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
from collections.abc import Iterable, Iterator, Mapping
from typing import Any, Final

from django.core.exceptions import NON_FIELD_ERRORS as DJANGO_NON_FIELD_ERRORS
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.utils.translation import gettext

from django_service_specs.parameters.coded_message import CodedMessage
from django_service_specs.parameters.non_field_errors import NON_FIELD_ERRORS
from django_service_specs.parameters.parameters import Parameter
from django_service_specs.settings import max_array_length
from django_service_specs.types.unknown_arguments import UnknownArguments

NON_FIELD_KEYS: Final = (NON_FIELD_ERRORS, DJANGO_NON_FIELD_ERRORS)
"""The keys a message about the whole input sits under: the kernel's, and Django's.

Django's is here because a service re-raising a model's ``message_dict`` as a
``ServiceValidationError`` carries its form-wide messages under ``"__all__"``.
Neither adds a step to the path a message is placed or printed with. Each is
held by its own test: test_non_field_errors_go_to_the_forms_own and
test_djangos_own_non_field_key_is_read_the_same."""


def refusal_messages(
    value: Any, path: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], str]]:
    """Every message below ``value``, each with its path from where the walk began: ``books.1.title``.

    The tree ``InvalidArguments`` carries: a row's index is a step of the path,
    and a ``NON_FIELD_KEYS`` key adds none. A list is the tree's leaf, so its
    messages share the path, and only a list: anything else is one message
    whatever its type, a lazy translation (which is not a ``str``) included, so
    it is never taken apart into characters. Read by every transport that
    prints or places a refusal, so each reads one tree one way.
    """
    if isinstance(value, Mapping):
        for key, inner in value.items():
            yield from refusal_messages(inner, path if key in NON_FIELD_KEYS else (*path, str(key)))
    elif isinstance(value, list):
        for inner in value:
            yield from refusal_messages(inner, path)
    else:
        yield path, str(value)


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
    # comparison: without it, every declared minimum is refused), whose
    # strictness test_a_minimum_at_the_default_maximum_is_met_by_a_list_of_exactly_that_many
    # holds: a minimum equal to the default is met by that many.
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
