"""``check_arguments`` - the shape check and the closed argument set, at every level."""

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
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.non_field_errors import NON_FIELD_ERRORS
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.parameters.utils import (
    expected_type,
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
    """The shape check: what a caller can get wrong that the declaration can see.

    Presence, JSON type, format, bounds, length, choices and nullability, at every
    level of nesting, with no query. It is what runs at enqueue time and in front of an
    untrusted caller's Validator, so a malformed call is refused before it costs
    a row lookup, and **it is no stricter than the libraries behind it**, with
    three exceptions named below: ASCII digits, a declared bound, and the
    length of an array. So a
    decimal accepts a JSON number as well as a string, because every decimal
    validator does, and a check stricter than the worker refuses what would
    have run.

    - A required parameter with a declared default is not refused when absent,
      because the Validator will supply the default. The default is not
      applied here: whether an omitted argument arrives as its default is the
      validating library's behaviour, not the shape check's.
    - **Under** ``partial=True`` **no absent parameter is refused**, at any
      depth: a partial update sends only what changes, and DRF skips an absent
      field anywhere below a partial serializer. A value that is present is
      checked as it would be otherwise, and an unknown key is still refused.
    - **A string is read as the number it spells** where an ``integer`` or a
      ``number`` is declared, wherever the declaration reaches, and the number
      is handed on: ``"3"`` is 3, ``"3.0"`` and ``" 3 "`` are 3 too, and a
      number's ``"1e3"`` is 1000.0. Django's forms and pydantic's lax mode
      both read these strings so, and the reading is the one ``coerce_flat``
      makes, which this shares. Where the two differ it is Django's: an
      integer's ``"5."`` and ``"5 .0"`` are 5, which pydantic's ``int``
      refuses, so this is looser than pydantic there. **The exception** is a
      string outside ASCII for an ``integer`` or a ``number``, not a
      ``decimal``: Django's fields read Arabic-Indic or fullwidth
      digits and Unicode spaces as Python's ``int`` does, and this refuses
      them, as pydantic and JSON do. A string that spells no such number is
      refused as the type it is not. The number goes on rather than the
      string because a Validator stricter than those two, the dataclass
      adapter's, refuses ``"3"`` for an ``int``.
    - ``bool`` is neither an ``integer`` nor a ``number``, although Python
      makes it an ``int``: a JSON ``true`` sent for a count is a caller's
      mistake, not the number one.
    - A ``file`` is a Django ``File``, and nothing else is one: no JSON value
      can be, so a JSON caller's string for it is refused at its name.
    - **An** ``any`` **is handed on as it arrived**: no type is declared, so
      nothing is read as a number, and ``"3"`` stays the string ``"3"``. A
      ``null`` is still refused unless it is ``nullable``, and NaN and the
      infinities are still no JSON value. A container is not walked, as an
      undeclared array element's is not, and a value of no JSON type - a
      Python caller's, or a multipart upload sent under its name - is handed
      on too.
    - **An integral float is an** ``integer``, and is handed on as an ``int``
      wherever the declaration reaches. JSON Schema counts ``5.0`` as an
      integer, so the ``{"type": "integer"}`` this kernel advertises admits
      it, and a Validator never sees ``5.0`` for an integer: its own type
      check and its bounds read the ``int``. ``5.5`` is still refused, and so
      are NaN and the infinities, which no integer is. A ``number`` keeps the
      float it was sent. **DRF reads it differently at an exponent**: its
      ``IntegerField`` reads ``str(value)``, as Django's form field does, so
      given ``1e16`` raw, both read ``"1e+16"`` and refuse it, where this
      check follows JSON Schema and hands on ``10000000000000000``, which
      either field then takes.
    - NaN and the infinities are refused wherever the declaration reaches.
      JSON has no spelling for either, so they are outside the ``number``
      type, and this is a type rule rather than a stricter check - although
      pydantic's ``float`` and the dataclass adapter's both take one.
    - ``minimum`` and ``maximum`` bound a number inclusively, in the words
      Django's ``MinValueValidator`` and ``MaxValueValidator`` use. **The
      second exception**: a bound is the declaration's, and may be stricter
      than the library behind it. ``filter_set_parameters`` draws
      django-filter's ``1e50`` below zero and on a range's bounds too, where
      django-filter draws none, because past it an integer column's
      conversion builds every digit of the value. A decimal string is
      compared as the decimal it spells, which reads its exponent and builds
      none of its digits, so ``"1E+999999999"`` is refused as fast as ``"2"``
      is taken. An array's bounds bound each element, refused at its index.
    - **An array's length** is read before any of its elements: within its
      ``min_length`` and ``max_length``, and where it declares no maximum,
      within the ``SERVICE_SPECS_MAX_ARRAY_LENGTH`` setting, 1000 unless the
      project says otherwise. **The third exception**, since that default is
      the kernel's and may be stricter than the library behind it: a list is
      a cost its caller controls the size of, one Validator run per row of a
      ``many`` call and one query variable per value of an ``in`` filter.
      The refusal is the list's own, at its name, in DRF's words.
    - ``choices`` constrain the value, and an array's choices constrain each of
      its elements, since an array is never one of a list of scalars. So do
      an array's ``format`` and bounds: a ``decimal`` array's elements are
      each read as a decimal is, and handed on as they were sent.
    - An ``object`` with no ``fields`` is free-form: its type is checked and
      its contents are not, because nothing is declared inside it to check
      against. An array with no ``items`` takes any element, and each is
      still one of the array's values: its choices and the finiteness rule
      reach it, while an element that is itself an object or an array is not
      walked.

    **The closed argument set applies at every level**, inside each row and
    each nested object as well as at the top. Closed only at the top, an
    unknown key in a row would reach the row's constructor and come back as a
    ``TypeError`` naming no row. ``REJECT`` refuses the key where it appeared;
    ``IGNORE`` drops it from the returned copy.

    Returns a cleaned copy and never modifies ``arguments``. The containers it
    walks are new - the top-level mapping, each declared object, each array -
    while a value it does not look inside, such as a free-form object, is
    passed through as the caller's. The values it replaces are the two it
    reads as numbers: an integral float declared an integer, and a numeric
    string declared either.

    Raises:
        InvalidArguments: carrying **every** problem found as one tree
            addressed by path, rather than the first; the tree's shape is
            documented on ``InvalidArguments``.
    """
    # Normalized, so the policy's plain value works and a misspelt one, or the
    # kept PASSTHROUGH member, raises here rather than quietly falling through
    # to one policy or the other
    # (test_passthrough_is_refused_where_the_policy_is_normalized).
    policy = unknown_arguments_policy(unknown_arguments)
    if not isinstance(arguments, Mapping):
        # A JSON-RPC caller controls the whole ``arguments`` value, so a list
        # there is a caller's mistake to refuse, not a crash to raise.
        raise InvalidArguments({NON_FIELD_ERRORS: [expected_type("object")]})
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
            # One branch to coverage, so each condition is held by its own test:
            # test_an_optional_parameter_may_be_absent_and_stays_absent,
            # test_a_required_parameter_with_a_default_is_not_refused_when_absent
            # and test_a_partial_call_may_leave_out_a_required_parameter_at_every_depth.
            if param.required and param.default is UNSET and not walk.partial:
                errors[param.name] = [CodedMessage(gettext("This field is required."), "required")]
            continue
        value, detail = _check_value(param, arguments[param.name], walk)
        if detail is None:
            cleaned[param.name] = value
        else:
            errors[param.name] = detail
    # Under IGNORE there is nothing to do: ``cleaned`` only ever receives a
    # declared name, so an undeclared one is dropped by never being copied.
    if walk.policy is UnknownArguments.REJECT:
        declared = parameters.names()
        for key in arguments:
            if key not in declared:
                # DRF has no code for it, since a serializer ignores a key it
                # does not declare; ``"unknown"`` names the policy that refused it.
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
            # ``any`` is the type an undeclared array element has, ``None``:
            # test_any_value_is_handed_on_unchanged fails without it.
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
        return None, [expected_type("array")]
    # The list whole, before any element is read, so one past its maximum
    # costs no per-element work: test_an_array_past_its_maximum_is_refused_before_any_element_is_read.
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
        # An array's format, choices and bounds describe each element, never
        # the list, whose own count is ``length_problem``'s. ``Parameter``
        # takes a format or a bound only on an element that can carry it.
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
    minimum: float | None = None,
    maximum: float | None = None,
    walk: _Walk,
) -> tuple[Any, Any]:
    """One value against one type: a parameter's own, or an array's element.

    ``json_type`` is ``None`` for the element of an array that declares no
    ``items``, which accepts anything.
    """
    # Read before the type check, which then sees a number and is unchanged.
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
        # Coded after the interpolation, since ``%`` on any ``str`` returns a plain one.
        message = gettext("Select a valid choice. %(value)s is not one of the available choices.")
        return None, [CodedMessage(message % {"value": value}, "invalid_choice")]
    return value, None


def _canonical(fmt: str | None, value: Any) -> Any:
    """``value`` in the one spelling its format reads, once the type check has passed it.

    A UUID's is ``str(uuid.UUID(value))``, so every reader - a permission
    check, the callable, a cache key - sees one spelling
    whichever of those a UUID column takes was sent: still a string, as the
    declaration is, never a ``uuid.UUID``. Every other value is unchanged.
    Held by test_a_uuid_is_handed_on_in_its_canonical_spelling.
    """
    return str(uuid.UUID(value)) if fmt == "uuid" else value


def _bound_problem(value: Any, minimum: float | None, maximum: float | None) -> CodedMessage | None:
    """The bound a well-typed number is past, or ``None``.

    Read only once the type check has passed, so ``value`` is an ``int``, a
    finite ``float`` or a string spelling a finite decimal, since ``Parameter``
    takes a bound on nothing else. The string is compared as a ``Decimal``,
    whose comparison with an ``int`` or a ``float`` is exact and reads the
    exponent first: it is never converted to the integer it may name, which
    for ``"1E+999999999"`` is a billion digits. A ``float`` bound is compared
    as the float it is, as django-filter's ``MaxValueValidator(1e50)`` is, so
    the two draw the line at the same value.

    The first test is one branch to coverage, and test_a_bound_may_stand_alone
    holds both conditions: without either, a parameter declaring only the
    other bound is never checked.
    """
    if minimum is None and maximum is None:
        return None
    number = Decimal(value) if isinstance(value, str) else value
    # Each ``is not None`` is held by test_a_bound_may_stand_alone, which
    # passes a number inside the one bound declared, so the absent one is
    # compared too: without the test, against ``None``, which raises.
    if maximum is not None and number > maximum:
        message = gettext("Ensure this value is less than or equal to %(limit_value)s.")
        return CodedMessage(message % {"limit_value": maximum}, "max_value")
    if minimum is not None and number < minimum:
        message = gettext("Ensure this value is greater than or equal to %(limit_value)s.")
        return CodedMessage(message % {"limit_value": minimum}, "min_value")
    return None


def _numeric(json_type: str | None, value: Any) -> Any:
    """``value``, or the number a string spells where an ``integer`` or a ``number`` is declared.

    ``coerce_flat``'s own reading, so the two accept the same strings. A string
    that spells no such number is left as it is, for the type check to refuse
    as the type it is not. One branch to coverage, so each condition is held by
    its own test: test_a_string_nothing_declares_a_number_stays_a_string (the
    type: without it, a plain string's ``"3"`` becomes a number) and
    test_true_is_still_no_number_and_no_integer (the string: without it,
    ``True`` reaches the parser, which takes no ``bool``).
    """
    if json_type in ("integer", "number") and isinstance(value, str):
        number = parse_number(json_type, value)
        return value if number is None else number
    return value


def _integral(json_type: str | None, value: Any) -> Any:
    """``value``, or the ``int`` an integral float declared an integer stands for.

    JSON Schema counts ``5.0`` as an integer, and the Validator is handed the
    int, so it never meets ``5.0`` for an integer. One branch to coverage, so
    each condition is held by its own test:
    ``test_a_float_nothing_declares_an_integer_stays_a_float`` (its ``number``:
    without the type, a number's float becomes an int), and
    ``test_refuses_a_value_of_another_json_type``, by its ``"three"`` (without
    the float, a string is asked ``is_integer``, and where an int has one,
    ``True`` becomes 1) and its ``1.5`` (without integral, ``int`` truncates it
    to an accepted 1). NaN and the infinities are not integral, so the type check
    refuses them as it did.
    """
    if json_type == "integer" and isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _type_problem(json_type: str | None, fmt: str | None, value: Any) -> CodedMessage | None:
    if fmt == "decimal":
        # A boolean is neither, although Python makes it an int: see _is_json_type.
        if not (_is_json_type("string", value) or _is_json_type("number", value)):
            return expected_type("decimal")
        try:
            finite = Decimal(value).is_finite()
        except InvalidOperation:
            finite = False
        # NaN and the infinities parse, and every decimal validator refuses them.
        return None if finite else CodedMessage(gettext("Enter a number."), "invalid")
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
    # declaration reaches. A container it leaves open is not walked, so one
    # inside is its Validator's. One branch to coverage: the type
    # condition is held by test_accepts_a_value_of_its_json_type[string-], the
    # finiteness one by test_accepts_a_value_of_its_json_type[number-2.5].
    if isinstance(value, float) and not math.isfinite(value):
        return CodedMessage(gettext("Enter a number."), "invalid")
    if fmt is None:
        return None
    if fmt == "uuid":
        return _uuid_problem(value)
    try:
        parsed = _DATE_PARSERS[fmt](value)
    except ValueError:
        # Well-formed but impossible, such as the thirtieth of February: Django
        # raises for that where it returns None for a malformed string, and to
        # the caller both are the same mistake.
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
    """Whether ``value`` spells a UUID, read as ``models.UUIDField.to_python`` reads one.

    The model field's parse is the reference because it is what a lookup on a
    UUID column runs: ``uuid.UUID`` over the string as sent. So the shape check
    refuses exactly what that lookup would raise ``ValidationError`` for -
    ``"null"``, ``"undefined"``, a parameter's own name echoed back, a value
    padded with whitespace - and passes every spelling the column takes:
    hyphenated or not, braced, ``urn:uuid:``, either case. ``forms.UUIDField``
    strips the padding first, so it passes what the model refuses. Held by
    test_a_uuid_is_refused_exactly_when_the_model_field_refuses_it and
    test_the_form_field_strips_what_the_model_field_refuses.

    A value that passes is handed on in its canonical spelling,
    ``str(uuid.UUID(value))``, so every reader sees one: still a string, as the
    declaration is on every route and a JSON wire has no other spelling for
    it, never a ``uuid.UUID``.
    """
    try:
        uuid.UUID(value)
    except ValueError:
        # The message ``forms.UUIDField`` gives, so Django's catalog translates it.
        return CodedMessage(gettext("Enter a valid UUID."), "invalid")
    return None


def _is_json_type(json_type: str, value: Any) -> bool:
    if isinstance(value, bool):
        return json_type == "boolean"
    return isinstance(value, _PYTHON_TYPES[json_type])
