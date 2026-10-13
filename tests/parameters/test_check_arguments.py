from __future__ import annotations

import dataclasses
import json
import sys
from decimal import Decimal
from types import MappingProxyType
from typing import Any

import pytest
from django import forms
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import translation

from django_service_specs.adapters.dataclass.dataclass_validator import DataclassValidator
from django_service_specs.adapters.forms.form_validator import FormValidator
from django_service_specs.parameters.check_arguments import check_arguments
from django_service_specs.parameters.coerce_flat import coerce_flat
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.parameters.utils import NON_FIELD_ERRORS
from django_service_specs.validation.unknown_arguments import UnknownArguments
from django_service_specs.validation.validation_context import ValidationContext
from tests.parameters.utils import coded

REQUIRED = "This field is required."
NULL = "This field cannot be null."
UNKNOWN = "Unknown argument."
NOT_A_NUMBER = "Enter a number."

PUBLISHER = Parameters.of(Parameter("name", "string", required=True))
BOOK = Parameters.of(
    Parameter("title", "string", required=True),
    Parameter("isbn", "string"),
    Parameter("publisher", "object", fields=PUBLISHER),
)
AUTHOR = Parameters.of(
    Parameter("name", "string", required=True),
    Parameter("books", "array", items=BOOK),
)
"""An author with books, each with a publisher: an object inside a row, two
levels below the top, which is as deep as a relation write goes in practice."""


def refusal(parameters: Parameters, arguments: Any, **kwargs: Any) -> dict[Any, Any]:
    with pytest.raises(InvalidArguments) as caught:
        check_arguments(parameters, arguments, **kwargs)
    return caught.value.detail


def one(parameter: Parameter) -> Parameters:
    return Parameters.of(parameter)


# --- a well-shaped call ------------------------------------------------------------


def test_returns_an_equal_copy_and_leaves_the_arguments_alone() -> None:
    arguments = {
        "name": "Le Guin",
        "books": ({"title": "Lathe", "publisher": {"name": "Scribner"}}, {"title": "Dispossessed"}),
    }
    before = {**arguments}
    cleaned = check_arguments(AUTHOR, arguments)
    assert cleaned == {
        "name": "Le Guin",
        "books": [{"title": "Lathe", "publisher": {"name": "Scribner"}}, {"title": "Dispossessed"}],
    }
    assert cleaned is not arguments
    assert cleaned["books"][0] is not arguments["books"][0]
    assert cleaned["books"][0]["publisher"] is not arguments["books"][0]["publisher"]
    assert arguments == before


def test_an_empty_declaration_takes_an_empty_call() -> None:
    assert check_arguments(Parameters(), {}) == {}


# --- presence -----------------------------------------------------------------------


def test_a_required_parameter_is_refused_when_absent() -> None:
    assert refusal(one(Parameter("pk", "integer", required=True)), {}) == {"pk": [REQUIRED]}


def test_an_optional_parameter_may_be_absent_and_stays_absent() -> None:
    # Holds the ``param.required`` condition in ``_check_object``. No default
    # is declared, so the other conjunct cannot be what lets it through.
    assert check_arguments(one(Parameter("pk", "integer")), {}) == {}


def test_a_required_parameter_with_a_default_is_not_refused_when_absent() -> None:
    # Holds the ``default is UNSET`` condition. The default is not applied
    # either: that is the Validator's library's behaviour to report.
    params = one(Parameter("status", "string", required=True, default="draft"))
    assert check_arguments(params, {}) == {}


def test_a_default_of_none_is_a_real_default() -> None:
    params = one(Parameter("note", "string", required=True, default=None))
    assert check_arguments(params, {}) == {}


# --- type -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("json_type", "value", "message"),
    [
        ("integer", True, "Expected an integer."),
        ("number", False, "Expected a number."),
        ("integer", 1.5, "Expected an integer."),
        ("integer", "three", "Expected an integer."),
        ("string", 3, "Expected a string."),
        ("boolean", "true", "Expected a boolean."),
        ("boolean", 1, "Expected a boolean."),
        ("array", "a,b", "Expected an array."),
        ("array", {"a": 1}, "Expected an array."),
        ("object", ["a"], "Expected an object."),
        ("integer", Decimal("3"), "Expected an integer."),
    ],
)
def test_refuses_a_value_of_another_json_type(json_type: str, value: Any, message: str) -> None:
    assert refusal(one(Parameter("x", json_type)), {"x": value}) == {"x": [message]}


@pytest.mark.parametrize(
    ("json_type", "value"),
    [
        ("integer", 3),
        ("number", 3),
        ("number", 2.5),
        ("string", ""),
        ("boolean", False),
        ("array", ["a"]),
        ("array", ("a",)),
        ("object", MappingProxyType({"a": 1})),
    ],
)
def test_accepts_a_value_of_its_json_type(json_type: str, value: Any) -> None:
    assert "x" in check_arguments(one(Parameter("x", json_type)), {"x": value})


@pytest.mark.parametrize(("value", "number"), [(5.0, 5), (-3.0, -3), (-0.0, 0), (1e16, 10**16)])
def test_an_integral_float_is_an_integer_and_is_handed_on_as_an_int(
    value: float, number: int
) -> None:
    # JSON Schema counts 5.0 as an integer, so the {"type": "integer"} the
    # kernel advertises admits it. 1e16 is one too, although a field reading
    # ``str(value)`` sees "1e+16" and refuses it.
    cleaned = check_arguments(one(Parameter("count", "integer")), {"count": value})
    assert cleaned == {"count": number}
    assert type(cleaned["count"]) is int


def test_a_field_reading_str_refuses_at_an_exponent_what_the_check_hands_on() -> None:
    # The divergence the check's docstring states, against the real field:
    # Django's IntegerField reads ``str(value)`` as DRF's does, so 1e16 raw is
    # "1e+16" and refused, while the int the check hands on is taken.
    field = forms.IntegerField()
    with pytest.raises(ValidationError):
        field.clean(1e16)
    cleaned = check_arguments(one(Parameter("count", "integer")), {"count": 1e16})
    assert field.clean(cleaned["count"]) == 10**16


def test_an_integral_float_is_an_int_wherever_the_declaration_reaches() -> None:
    # Equality cannot tell 5.0 from 5, so the repr is what is compared.
    params = Parameters.of(
        Parameter("count", "integer"),
        Parameter("ids", "array", items="integer", items_nullable=True),
        Parameter("box", "object", fields=Parameters.of(Parameter("size", "integer"))),
        Parameter("lines", "array", items=Parameters.of(Parameter("qty", "integer"))),
        Parameter("rank", "integer", choices=(1, 2)),
    )
    arguments = {
        "count": 5.0,
        "ids": [1.0, None, 2],
        "box": {"size": 3.0},
        "lines": [{"qty": 4.0}],
        "rank": 2.0,
    }
    expected = {
        "count": 5,
        "ids": [1, None, 2],
        "box": {"size": 3},
        "lines": [{"qty": 4}],
        "rank": 2,
    }
    assert repr(check_arguments(params, arguments)) == repr(expected)
    assert arguments["box"] == {"size": 3.0}
    assert repr(arguments["box"]["size"]) == "3.0"


def test_a_choice_refused_after_the_conversion_names_the_int() -> None:
    params = one(Parameter("rank", "integer", choices=(1, 2)))
    assert refusal(params, {"rank": 3.0}) == {
        "rank": ["Select a valid choice. 3 is not one of the available choices."]
    }


@pytest.mark.parametrize(
    ("parameter", "value"),
    [
        (Parameter("x", "number"), 5.0),
        (Parameter("x", "array"), [5.0]),
        (Parameter("x", "object"), {"size": 5.0}),
    ],
    ids=["number", "untyped-element", "free-form-object"],
)
def test_a_float_nothing_declares_an_integer_stays_a_float(
    parameter: Parameter, value: Any
) -> None:
    # Holds ``json_type == "integer"`` in the conversion: a number keeps the
    # float the caller sent, and what an undeclared element or a free-form
    # object holds is the caller's, for its Validator.
    assert repr(check_arguments(one(parameter), {"x": value})["x"]) == repr(value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_float_is_still_no_integer(value: float) -> None:
    # Neither is integral, so neither is converted, and the type check
    # answers as it did before an integral float was an integer.
    assert refusal(one(Parameter("count", "integer")), {"count": value}) == {
        "count": ["Expected an integer."]
    }


def test_the_validator_reads_the_int_so_its_own_type_and_bounds_apply() -> None:
    # The dataclass adapter refuses a float for an ``int``, so it passing here
    # is the int the check handed on; the form's bounds read that same int.
    @dataclasses.dataclass
    class Counted:
        count: int

    strict = DataclassValidator(Counted)
    cleaned = check_arguments(strict.parameters(), {"count": 2.0})
    assert repr(strict.validate(cleaned, ValidationContext(principal=None))) == "{'count': 2}"

    class Bounded(forms.Form):
        count = forms.IntegerField(min_value=1, max_value=10)

    bounded = FormValidator(Bounded)
    with pytest.raises(InvalidArguments) as caught:
        bounded.validate(
            check_arguments(bounded.parameters(), {"count": 11.0}),
            ValidationContext(principal=None),
        )
    assert caught.value.detail == {"count": ["Ensure this value is less than or equal to 10."]}


# --- a number sent as a string ---------------------------------------------------------


@pytest.mark.parametrize(
    ("json_type", "value", "number"),
    [
        ("integer", "3", 3),
        ("integer", "3.0", 3),
        ("integer", " 3 ", 3),
        ("integer", "-4.", -4),
        # A number's integer spelling is the exact int a JSON decoder makes of it.
        ("number", "3", 3),
        ("number", "3.0", 3.0),
        ("number", " 3 ", 3),
        ("number", "1e3", 1000.0),
        ("number", "2.5", 2.5),
    ],
)
def test_a_numeric_string_is_read_and_the_number_handed_on(
    json_type: str, value: str, number: float
) -> None:
    # Django's forms read every one of these strings as the number, and
    # pydantic's lax mode all but the integer "-4.", so refusing them was
    # stricter than every library behind the check. The parsed number is what goes on: a dataclass Validator refuses
    # the string "3" for an ``int``.
    cleaned = check_arguments(one(Parameter("x", json_type)), {"x": value})
    assert cleaned == {"x": number}
    assert type(cleaned["x"]) is type(number)


@pytest.mark.parametrize(
    ("json_type", "value", "message"),
    [
        ("integer", "1e3", "Expected an integer."),
        ("integer", "3.5", "Expected an integer."),
        ("integer", "", "Expected an integer."),
        ("number", "nan", "Expected a number."),
        ("number", "inf", "Expected a number."),
        ("number", "three", "Expected a number."),
    ],
)
def test_a_string_that_is_no_number_is_refused_as_its_type(
    json_type: str, value: str, message: str
) -> None:
    # The refusal is the type's, as before: a string that does not read as the
    # number is a string, which is not the declared type. "1e3" is no integer
    # to Django's forms or pydantic, although both read it as a number.
    assert refusal(one(Parameter("x", json_type)), {"x": value}) == {"x": [message]}


@pytest.mark.parametrize(
    "value",
    ["3", "3.0", " 3 ", "-4.", "1e3", "3.5", "", "abc", "nan", "inf", "1_000", "\u0665", "\u00a03"],
)
@pytest.mark.parametrize("json_type", ["integer", "number"])
def test_a_numeric_string_is_accepted_exactly_where_coerce_flat_accepts_it(
    json_type: str, value: str
) -> None:
    # One rule for both, input for input, so a query string and a JSON body
    # carrying the same string reach the Validator as the same value.
    params = one(Parameter("x", json_type))
    try:
        flat: Any = coerce_flat(params, {"x": value})
    except InvalidArguments:
        flat = None
    try:
        checked: Any = check_arguments(params, {"x": value})
    except InvalidArguments:
        checked = None
    assert checked == flat


@pytest.mark.parametrize("value", ["\u0665", "\uff15", "\u0665.0", "\u00a05"])
def test_a_numeric_string_spelled_outside_ascii_is_refused_as_its_type(value: str) -> None:
    # Python's ``int`` and ``float`` read Arabic-Indic and fullwidth digits, and
    # a no-break space around them, and pydantic's lax mode reads none of them.
    assert refusal(
        Parameters.of(Parameter("count", "integer"), Parameter("ratio", "number")),
        {"count": value, "ratio": value},
    ) == {"count": ["Expected an integer."], "ratio": ["Expected a number."]}


@pytest.mark.parametrize(
    ("value", "number"),
    [(str(2**53 + 1), 2**53 + 1), ("-12", -12), ("12.5", 12.5), ("1e3", 1000.0)],
)
def test_a_number_s_string_is_handed_on_as_a_json_decoder_reads_its_digits(
    value: str, number: float
) -> None:
    # A JSON body carrying the literal 9007199254740993 hands on that exact
    # ``int``; the same digits sent as a string are read the same way, not
    # rounded through ``float`` to their neighbour.
    checked = check_arguments(one(Parameter("x", "number")), {"x": value})["x"]
    assert checked == number
    assert type(checked) is type(number)


def test_a_number_s_string_past_int_s_digit_limit_is_refused_never_rounded() -> None:
    # Zero-padded past the 4300 digits ``int`` reads from Python 3.10.7 on,
    # these digits are still a finite ``float``, 2**53: refused as no number
    # rather than handed on as that neighbour. With no limit they are exact.
    padded = "0" * 4300 + str(2**53 + 1)
    params = one(Parameter("x", "number"))
    if getattr(sys, "get_int_max_str_digits", lambda: 0)() != 0:
        assert refusal(params, {"x": padded}) == {"x": ["Expected a number."]}
    else:
        assert check_arguments(params, {"x": padded}) == {"x": 2**53 + 1}
    long = "9" * 4301
    assert refusal(params, {"x": long}) == {"x": ["Expected a number."]}
    integer = one(Parameter("x", "integer"))
    assert refusal(integer, {"x": long}) == {"x": ["Expected an integer."]}


@pytest.mark.parametrize("value", ["12.50", "\u0665", "\uff15", "\u0661\u0662.\u0665", " 5 "])
def test_a_decimal_string_is_read_as_decimal_reads_it_in_any_digit_script(value: str) -> None:
    # Not a number's reading: a decimal is checked as Python's ``Decimal``
    # parses it, which takes Arabic-Indic and fullwidth digits, and is handed
    # on unchanged. Deliberately: Django's ``DecimalField``, DRF's and
    # pydantic's ``Decimal`` each hand the string to ``Decimal`` and take them,
    # so refusing them would be stricter than every Validator behind the check.
    params = one(Parameter("price", "string", format="decimal"))
    assert check_arguments(params, {"price": value}) == {"price": value}


def test_true_is_still_no_number_and_no_integer() -> None:
    params = Parameters.of(Parameter("count", "integer"), Parameter("ratio", "number"))
    assert refusal(params, {"count": True, "ratio": True}) == {
        "count": ["Expected an integer."],
        "ratio": ["Expected a number."],
    }


def test_a_numeric_string_is_read_wherever_the_declaration_reaches() -> None:
    params = Parameters.of(
        Parameter("ids", "array", items="integer"),
        Parameter("box", "object", fields=Parameters.of(Parameter("size", "number"))),
        Parameter("lines", "array", items=Parameters.of(Parameter("qty", "integer"))),
        Parameter("rank", "integer", choices=(1, 2)),
    )
    arguments = {"ids": ["1", 2], "box": {"size": "2.5"}, "lines": [{"qty": "4"}], "rank": "2"}
    expected = {"ids": [1, 2], "box": {"size": 2.5}, "lines": [{"qty": 4}], "rank": 2}
    assert repr(check_arguments(params, arguments)) == repr(expected)


@pytest.mark.parametrize(
    "parameter",
    [
        Parameter("x", "string"),
        Parameter("x", "string", format="decimal"),
        Parameter("x", "array"),
        Parameter("x", "object"),
    ],
    ids=["string", "decimal", "untyped-element", "free-form-object"],
)
def test_a_string_nothing_declares_a_number_stays_a_string(parameter: Parameter) -> None:
    # Holds the type condition of the reading: a decimal is decoded by its
    # Validator from the string, and what an undeclared element or a
    # free-form object holds is the caller's.
    value: Any = {"string": "3", "array": ["3"], "object": {"n": "3"}}[parameter.type]
    assert repr(check_arguments(one(parameter), {"x": value})["x"]) == repr(value)


def test_a_tuple_comes_back_as_a_list() -> None:
    assert check_arguments(one(Parameter("x", "array")), {"x": ("a", "b")}) == {"x": ["a", "b"]}


def test_a_free_form_object_is_passed_through_as_the_callers() -> None:
    # Nothing is declared inside it, so nothing inside it is checked or closed.
    value = {"anything": {"at": ["all"]}}
    assert check_arguments(one(Parameter("x", "object")), {"x": value})["x"] is value


# --- a file -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [SimpleUploadedFile("notes.txt", b"A file."), ContentFile(b"A file.", name="notes.txt")],
    ids=["uploaded", "content"],
)
def test_a_file_takes_a_django_file_and_hands_on_the_same_object(value: Any) -> None:
    # An upload is a ``File``, and so is the ``ContentFile`` a command or a task
    # builds, so a Python caller sends a file the way a request's body does.
    cleaned = check_arguments(one(Parameter("notes", "file")), {"notes": value})
    assert cleaned["notes"] is value


@pytest.mark.parametrize("value", ["notes.txt", b"A file.", {"name": "notes.txt"}, 3])
def test_a_file_refuses_anything_that_is_not_a_file(value: Any) -> None:
    # No JSON value is a file: a path or the file's bytes sent as a string is
    # the caller's mistake, refused at its name rather than handed to the
    # Validator to fail on.
    assert refusal(one(Parameter("notes", "file")), {"notes": value}) == {
        "notes": ["Expected a file."]
    }


def test_an_array_of_files_checks_each_element() -> None:
    attached = SimpleUploadedFile("a.txt", b"A.")
    params = one(Parameter("notes", "array", items="file"))
    assert check_arguments(params, {"notes": [attached]}) == {"notes": [attached]}
    assert refusal(params, {"notes": [attached, "b.txt"]}) == {"notes": {1: ["Expected a file."]}}


def test_a_file_is_absent_or_null_by_the_same_rules_as_any_parameter() -> None:
    assert refusal(one(Parameter("notes", "file", required=True)), {}) == {"notes": [REQUIRED]}
    assert check_arguments(one(Parameter("notes", "file", nullable=True)), {"notes": None}) == {
        "notes": None
    }


# --- format -----------------------------------------------------------------------------

DECIMAL = one(Parameter("price", "string", format="decimal"))


@pytest.mark.parametrize("value", ["9.99", " 9.99 ", "-1e3", 3, 2.5])
def test_a_decimal_accepts_a_string_or_a_json_number(value: Any) -> None:
    assert check_arguments(DECIMAL, {"price": value}) == {"price": value}


@pytest.mark.parametrize("value", [True, ["9.99"]])
def test_a_decimal_refuses_what_is_neither_a_string_nor_a_number(value: Any) -> None:
    # A boolean would parse - Decimal(True) is 1 - so the type message, not the
    # parse message, is what proves the type check answered.
    message = "Expected a decimal string or a number."
    assert refusal(DECIMAL, {"price": value}) == {"price": [message]}
    assert message != NOT_A_NUMBER


@pytest.mark.parametrize("value", ["abc", "", "NaN", "Infinity", "-inf"])
def test_a_decimal_string_must_parse_to_a_finite_number(value: str) -> None:
    assert refusal(DECIMAL, {"price": value}) == {"price": [NOT_A_NUMBER]}


def test_a_decimal_float_must_be_finite() -> None:
    assert refusal(DECIMAL, {"price": float("nan")}) == {"price": [NOT_A_NUMBER]}


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_number_must_be_finite(value: float) -> None:
    # No JSON value is one, and Python's decoder reads an overflowing literal
    # such as 1e400 as an infinity.
    assert refusal(one(Parameter("ratio", "number")), {"ratio": value}) == {"ratio": [NOT_A_NUMBER]}


def test_an_untyped_element_must_be_finite_too() -> None:
    # Whatever the declaration leaves open, it cannot be a value JSON has no
    # spelling for.
    assert refusal(one(Parameter("tags", "array")), {"tags": ["a", float("inf")]}) == {
        "tags": {1: [NOT_A_NUMBER]}
    }


def test_a_non_finite_value_inside_a_free_form_object_is_its_validators() -> None:
    # Nothing is declared inside it, so the type rule has nothing to reach, as
    # no other rule does; an object or array element of an untyped array, and
    # an array element of an array of arrays, are the same.
    blob, row = {"ratio": float("nan")}, [float("nan")]
    assert check_arguments(one(Parameter("x", "object")), {"x": blob})["x"] is blob
    assert check_arguments(one(Parameter("xs", "array")), {"xs": [blob]})["xs"][0] is blob
    assert check_arguments(one(Parameter("xs", "array")), {"xs": [row]})["xs"][0] is row
    nested = one(Parameter("xs", "array", items="array"))
    assert check_arguments(nested, {"xs": [row]})["xs"][0] is row


DATE_TIME = one(Parameter("at", "string", format="date-time"))
DATE = one(Parameter("on", "string", format="date"))


@pytest.mark.parametrize("value", ["2024-01-31T10:00:00Z", "2024-01-31 10:00", "2024-01-31"])
def test_a_date_time_is_what_djangos_parser_reads(value: str) -> None:
    assert check_arguments(DATE_TIME, {"at": value}) == {"at": value}


@pytest.mark.parametrize(
    "value",
    [
        "yesterday",
        # Well-formed and impossible: Django raises ValueError for this one
        # rather than returning None, and it must be a refusal, not a crash.
        "2024-02-30T10:00:00",
    ],
)
def test_a_date_time_that_does_not_parse_is_refused(value: str) -> None:
    assert refusal(DATE_TIME, {"at": value}) == {"at": ["Enter a valid date/time."]}


@pytest.mark.parametrize("value", ["soon", "2024-02-30"])
def test_a_date_that_does_not_parse_is_refused(value: str) -> None:
    assert refusal(DATE, {"on": value}) == {"on": ["Enter a valid date."]}


def test_a_date_is_what_djangos_parser_reads() -> None:
    assert check_arguments(DATE, {"on": "2024-01-31"}) == {"on": "2024-01-31"}


def test_a_formatted_string_is_type_checked_before_it_is_parsed() -> None:
    assert refusal(DATE, {"on": 20240131}) == {"on": ["Expected a string."]}


# --- choices ---------------------------------------------------------------------------

STATUS = one(Parameter("status", "string", choices=("draft", "published")))


def test_a_value_of_the_right_type_outside_the_choices_is_refused() -> None:
    assert refusal(STATUS, {"status": "archived"}) == {
        "status": ["Select a valid choice. archived is not one of the available choices."]
    }


def test_a_value_among_the_choices_is_accepted() -> None:
    assert check_arguments(STATUS, {"status": "draft"}) == {"status": "draft"}


def test_the_type_check_answers_before_the_choices() -> None:
    # True == 1 in Python, so ``True in (1, 2)`` holds and only the type check
    # stands between a boolean and an integer choice.
    params = one(Parameter("rank", "integer", choices=(1, 2)))
    detail = refusal(params, {"rank": True})
    assert detail == {"rank": ["Expected an integer."]}
    assert "valid choice" not in str(detail)


# --- nullability --------------------------------------------------------------------------


def test_null_is_refused_unless_the_parameter_is_nullable() -> None:
    assert refusal(one(Parameter("x", "string")), {"x": None}) == {"x": [NULL]}


def test_null_is_a_value_for_a_nullable_parameter_even_a_required_one() -> None:
    params = one(Parameter("x", "string", required=True, nullable=True, choices=("a",)))
    assert check_arguments(params, {"x": None}) == {"x": None}


# --- flat arrays ----------------------------------------------------------------------------


def test_a_flat_array_checks_each_element_and_addresses_only_the_failures() -> None:
    # Holds the ``rows is not None`` condition in ``_check_value``: an element's
    # message stays a bare list at its index, where a row's own goes under
    # non_field_errors.
    params = one(Parameter("ids", "array", items="integer"))
    assert refusal(params, {"ids": [1, "two", 3, True, None]}) == {
        "ids": {
            1: ["Expected an integer."],
            3: ["Expected an integer."],
            4: ["Expected an integer."],
        }
    }


def test_an_arrays_choices_constrain_each_element() -> None:
    params = one(Parameter("tags", "array", items="string", choices=("a", "b")))
    assert check_arguments(params, {"tags": ["b", "a"]}) == {"tags": ["b", "a"]}
    assert refusal(params, {"tags": ["a", "c"]}) == {
        "tags": {1: ["Select a valid choice. c is not one of the available choices."]}
    }


def test_a_null_element_is_kept_where_the_element_is_nullable() -> None:
    # A gap in the list, as ``list[int | None]`` holds one: kept at its index
    # and read against neither the element's type nor its choices, while every
    # other element still is.
    params = one(Parameter("ids", "array", items="integer", items_nullable=True, choices=(1, 2)))
    assert check_arguments(params, {"ids": [1, None, 2]}) == {"ids": [1, None, 2]}
    assert refusal(params, {"ids": [None, "two", 3]}) == {
        "ids": {
            1: ["Expected an integer."],
            2: ["Select a valid choice. 3 is not one of the available choices."],
        }
    }


def test_a_nullable_element_leaves_the_array_itself_not_nullable() -> None:
    params = one(Parameter("ids", "array", items="integer", items_nullable=True))
    assert refusal(params, {"ids": None}) == {"ids": [NULL]}


def test_an_array_with_no_items_accepts_any_element() -> None:
    # Holds the ``json_type is not None`` condition in ``_type_problem``.
    params = one(Parameter("anything", "array"))
    values = [1, "a", None, {"b": 2}]
    assert check_arguments(params, {"anything": values}) == {"anything": values}


# --- rows and nested objects ------------------------------------------------------------------


def test_rows_are_addressed_by_int_index_and_only_the_failing_ones() -> None:
    # Holds the ``isinstance(detail, list)`` condition in ``_check_value``: a
    # row's field errors are a tree already and are not wrapped again.
    books = [{"title": "Lathe"}, {"isbn": "123"}, {"title": "Dispossessed"}]
    assert refusal(AUTHOR, {"name": "Le Guin", "books": books}) == {
        "books": {1: {"title": [REQUIRED]}}
    }


def test_a_row_that_is_not_an_object_is_refused_under_non_field_errors_in_the_row() -> None:
    detail = refusal(AUTHOR, {"name": "Le Guin", "books": ["Lathe", None]})
    assert detail == {
        "books": {
            0: {NON_FIELD_ERRORS: ["Expected an object."]},
            1: {NON_FIELD_ERRORS: ["Expected an object."]},
        }
    }


def test_a_null_row_is_kept_where_the_rows_are_nullable() -> None:
    params = one(Parameter("books", "array", items=BOOK, items_nullable=True))
    assert check_arguments(params, {"books": [{"title": "Lathe"}, None]}) == {
        "books": [{"title": "Lathe"}, None]
    }
    # A row that is there is still checked and closed.
    assert refusal(params, {"books": [None, {"isbn": "1"}]}) == {
        "books": {1: {"title": [REQUIRED]}}
    }


def test_an_object_inside_a_row_is_checked_two_levels_down() -> None:
    books = [
        {"title": "Lathe", "publisher": "Scribner"},
        {"title": "Dispossessed", "publisher": {}},
        {"title": "Earthsea", "publisher": {"name": "Parnassus"}},
    ]
    assert refusal(AUTHOR, {"name": "Le Guin", "books": books}) == {
        "books": {
            0: {"publisher": ["Expected an object."]},
            1: {"publisher": {"name": [REQUIRED]}},
        }
    }


def test_an_object_parameter_given_a_non_mapping_is_a_type_error_at_the_field() -> None:
    params = one(Parameter("publisher", "object", fields=PUBLISHER))
    assert refusal(params, {"publisher": ["Scribner"]}) == {"publisher": ["Expected an object."]}


def test_arguments_that_are_not_a_mapping_are_refused_at_the_root() -> None:
    assert refusal(AUTHOR, ["Le Guin"]) == {NON_FIELD_ERRORS: ["Expected an object."]}


# --- a partial call ----------------------------------------------------------------------


def test_a_partial_call_may_leave_out_a_required_parameter_at_every_depth() -> None:
    # An update that sends only what changes, as DRF reads ``partial``: a
    # field that is absent is skipped, whether at the top, inside a nested
    # object or inside a row.
    books = [{"isbn": "1", "publisher": {}}]
    assert check_arguments(AUTHOR, {"books": books}, partial=True) == {"books": books}
    assert check_arguments(AUTHOR, {}, partial=True) == {}


def test_a_partial_call_still_checks_what_it_sends() -> None:
    books = [{"title": 3, "publisher": {"name": None}}]
    assert refusal(AUTHOR, {"name": 5, "books": books}, partial=True) == {
        "name": ["Expected a string."],
        "books": {0: {"title": ["Expected a string."], "publisher": {"name": [NULL]}}},
    }


def test_a_partial_call_still_refuses_an_unknown_key_at_every_level() -> None:
    books = [{"subtitle": "x", "publisher": {"city": "NY"}}]
    assert refusal(AUTHOR, {"colour": "red", "books": books}, partial=True) == {
        "colour": [UNKNOWN],
        "books": {0: {"subtitle": [UNKNOWN], "publisher": {"city": [UNKNOWN]}}},
    }


def test_a_call_is_not_partial_by_default() -> None:
    # Holds ``not partial`` in the presence guard alongside
    # test_a_required_parameter_is_refused_when_absent.
    assert refusal(AUTHOR, {"books": [{}]}, partial=False) == {
        "name": [REQUIRED],
        "books": {0: {"title": [REQUIRED]}},
    }


# --- the closed argument set ---------------------------------------------------------------------

INTRUDED = {
    "name": "Le Guin",
    "tenant": "acme",
    "books": [
        {"title": "Lathe", "tenant": "acme"},
        {"title": "Earthsea", "publisher": {"name": "Parnassus", "tenant": "acme"}},
    ],
}


def test_reject_refuses_an_undeclared_key_at_the_level_it_appeared() -> None:
    assert refusal(AUTHOR, INTRUDED) == {
        "tenant": [UNKNOWN],
        "books": {
            0: {"tenant": [UNKNOWN]},
            1: {"publisher": {"tenant": [UNKNOWN]}},
        },
    }


def test_reject_is_the_default() -> None:
    assert refusal(AUTHOR, INTRUDED) == refusal(
        AUTHOR, INTRUDED, unknown_arguments=UnknownArguments.REJECT
    )


def test_ignore_drops_an_undeclared_key_at_every_level_and_leaves_the_input_alone() -> None:
    cleaned = check_arguments(AUTHOR, INTRUDED, unknown_arguments=UnknownArguments.IGNORE)
    assert cleaned == {
        "name": "Le Guin",
        "books": [{"title": "Lathe"}, {"title": "Earthsea", "publisher": {"name": "Parnassus"}}],
    }
    assert INTRUDED["tenant"] == "acme"
    assert INTRUDED["books"][0]["tenant"] == "acme"
    assert INTRUDED["books"][1]["publisher"]["tenant"] == "acme"


def test_ignore_still_refuses_what_is_declared_and_wrong() -> None:
    arguments = {"name": 3, "tenant": "acme"}
    assert refusal(AUTHOR, arguments, unknown_arguments=UnknownArguments.IGNORE) == {
        "name": ["Expected a string."]
    }


def test_the_policy_may_be_given_by_value_and_an_unknown_one_is_a_programming_error() -> None:
    cleaned = check_arguments(AUTHOR, {"name": "Le Guin", "x": 1}, unknown_arguments="ignore")
    assert cleaned == {"name": "Le Guin"}
    with pytest.raises(ValueError, match="passthrough"):
        check_arguments(AUTHOR, {"name": "Le Guin"}, unknown_arguments="passthrough")


# --- every problem at once --------------------------------------------------------------------------


def test_every_problem_is_reported_in_one_tree() -> None:
    arguments = {
        "tenant": "acme",
        "books": [
            {"title": 3},
            {"title": "Lathe"},
            {"title": "Earthsea", "publisher": {"name": None}, "tenant": "acme"},
            7,
        ],
    }
    assert refusal(AUTHOR, arguments) == {
        "name": [REQUIRED],
        "tenant": [UNKNOWN],
        "books": {
            0: {"title": ["Expected a string."]},
            2: {"publisher": {"name": [NULL]}, "tenant": [UNKNOWN]},
            3: {NON_FIELD_ERRORS: ["Expected an object."]},
        },
    }


# --- bounds ------------------------------------------------------------------------------------

ABOVE = "Ensure this value is less than or equal to %s."
BELOW = "Ensure this value is greater than or equal to %s."


@pytest.mark.parametrize("value", [1, 10, "10", 5.0])
def test_a_bound_on_an_integer_is_inclusive(value: Any) -> None:
    params = one(Parameter("n", "integer", minimum=1, maximum=10))
    assert check_arguments(params, {"n": value}) == {"n": int(value)}


@pytest.mark.parametrize(
    ("value", "message"), [(0, BELOW % 1), (11, ABOVE % 10), ("11", ABOVE % 10)]
)
def test_an_integer_past_a_bound_is_refused_in_django_s_words(value: Any, message: str) -> None:
    params = one(Parameter("n", "integer", minimum=1, maximum=10))
    assert refusal(params, {"n": value}) == {"n": [message]}


def test_a_bound_may_stand_alone() -> None:
    # Each value sits inside the one bound declared, so the side left open is
    # compared too: read against ``None`` it would raise.
    floor = one(Parameter("n", "number", minimum=0))
    ceiling = one(Parameter("n", "number", maximum=0))
    assert check_arguments(floor, {"n": 5.5}) == {"n": 5.5}
    assert check_arguments(ceiling, {"n": -5.5}) == {"n": -5.5}
    assert refusal(floor, {"n": -0.5}) == {"n": [BELOW % 0]}
    assert refusal(ceiling, {"n": 0.5}) == {"n": [ABOVE % 0]}


@pytest.mark.parametrize(
    ("value", "detail"),
    [
        ("1e50", None),
        ("-1e50", None),
        (" 12.5 ", None),
        (1e49, None),
        # Read by exponent, never built as the integer it names. A cheap one
        # all the same: a regression elsewhere must fail here, not hang.
        ("1e400", [ABOVE % "1e+50"]),
        ("-1e400", [BELOW % "-1e+50"]),
        ("1.0000000000000001e50", [ABOVE % "1e+50"]),
        (1e60, [ABOVE % "1e+50"]),
        (-1e60, [BELOW % "-1e+50"]),
    ],
)
def test_a_decimal_is_compared_as_the_decimal_it_spells(value: Any, detail: Any) -> None:
    params = one(Parameter("price", "string", format="decimal", minimum=-1e50, maximum=1e50))
    if detail is None:
        assert check_arguments(params, {"price": value}) == {"price": value}
    else:
        assert refusal(params, {"price": value}) == {"price": detail}


# --- an array's element: its format and its bounds ------------------------------------------

FORTY_DIGITS = "0.1234567890123456789012345678901234567891"
"""A fraction no float holds: read through one, it comes back as 0.12345678901234568."""


def _decimals() -> Parameters:
    """A django-filter CSV number filter's declaration, built in the test so a tree refusing it fails there."""
    return one(
        Parameter("pks", "array", items="string", format="decimal", minimum=-1e50, maximum=1e50)
    )


def test_each_element_of_a_decimal_array_is_handed_on_as_it_was_sent() -> None:
    # Exact: a string stays the string it spells, never a float on the way, and
    # a JSON number is taken as a scalar decimal takes one.
    sent = ["1", 2, FORTY_DIGITS, " 12.5 ", 1.5, "1e50", "-1e50"]
    assert check_arguments(_decimals(), {"pks": sent}) == {"pks": sent}


def test_an_element_past_its_bound_is_refused_at_its_index_with_django_s_code() -> None:
    # Compared by exponent, so a billion-digit integer is never built: a
    # regression must fail here rather than hang the suite.
    detail = refusal(_decimals(), {"pks": ["1", "1E+999999999", "-1E+999999999", 1e60]})
    assert coded(detail) == {
        "pks": {
            1: [(ABOVE % "1e+50", "max_value")],
            2: [(BELOW % "-1e+50", "min_value")],
            3: [(ABOVE % "1e+50", "max_value")],
        }
    }


def test_an_element_that_spells_no_decimal_is_refused_at_its_index() -> None:
    detail = refusal(_decimals(), {"pks": ["1", "x", "", True, "NaN", None]})
    assert coded(detail) == {
        "pks": {
            1: [(NOT_A_NUMBER, "invalid")],
            2: [(NOT_A_NUMBER, "invalid")],
            3: [("Expected a decimal string or a number.", "invalid")],
            4: [(NOT_A_NUMBER, "invalid")],
            # A gap the element does not allow is refused as the type it is not.
            5: [("Expected a decimal string or a number.", "invalid")],
        }
    }


def test_a_decimal_array_s_null_element_is_kept_where_its_element_is_nullable() -> None:
    params = one(
        Parameter("pks", "array", items="string", format="decimal", maximum=1, items_nullable=True)
    )
    assert check_arguments(params, {"pks": ["1", None]}) == {"pks": ["1", None]}
    assert refusal(params, {"pks": [None, "2"]}) == {"pks": {1: [ABOVE % 1]}}


@pytest.mark.parametrize("items", ["integer", "number"])
def test_each_element_of_a_number_array_is_bounded(items: str) -> None:
    params = one(Parameter("ids", "array", items=items, minimum=1, maximum=10))
    assert check_arguments(params, {"ids": [1, "10", 5.0]}) == {"ids": [1, 10, 5]}
    assert coded(refusal(params, {"ids": [1, 11, "0"]})) == {
        "ids": {1: [(ABOVE % 10, "max_value")], 2: [(BELOW % 1, "min_value")]}
    }


def test_a_value_of_the_wrong_type_is_refused_as_that_not_as_out_of_bounds() -> None:
    params = one(Parameter("price", "string", format="decimal", maximum=1))
    assert refusal(params, {"price": "lots"}) == {"price": [NOT_A_NUMBER]}


def test_a_bound_message_is_translated_through_djangos_own_catalog() -> None:
    params = one(Parameter("n", "integer", maximum=10))
    with translation.override("de"):
        detail = refusal(params, {"n": 11})
        expected = translation.gettext(
            "Ensure this value is less than or equal to %(limit_value)s."
        )
    assert "%(limit_value)s" in expected
    assert expected != ABOVE.replace("%s", "%(limit_value)s")
    assert detail == {"n": [expected % {"limit_value": 10}]}


# --- array length ------------------------------------------------------------------------------------

TOO_MANY = "Ensure this field has no more than %s elements."
TOO_FEW = "Ensure this field has at least %s elements."
IDS = one(Parameter("ids", "array", items="integer"))


def test_an_array_takes_a_thousand_elements_and_no_more_by_default() -> None:
    # The boundary pair, so the default itself is held: 1000 is Django's own
    # DATA_UPLOAD_MAX_NUMBER_FIELDS, the line a form body already stops at.
    assert check_arguments(IDS, {"ids": list(range(1000))}) == {"ids": list(range(1000))}
    assert refusal(IDS, {"ids": list(range(1001))}) == {"ids": [TOO_MANY % 1000]}


def test_an_array_past_its_maximum_is_refused_before_any_element_is_read() -> None:
    # Every element is malformed, and none is addressed: the list is refused
    # whole, so a long list costs no per-element work.
    detail = refusal(IDS, {"ids": ["x"] * 1001})
    assert detail == {"ids": [TOO_MANY % 1000]}


@override_settings(SERVICE_SPECS_MAX_ARRAY_LENGTH=3)
def test_the_setting_moves_the_default_maximum() -> None:
    assert check_arguments(IDS, {"ids": [1, 2, 3]}) == {"ids": [1, 2, 3]}
    assert refusal(IDS, {"ids": [1, 2, 3, 4]}) == {"ids": [TOO_MANY % 3]}


@override_settings(SERVICE_SPECS_MAX_ARRAY_LENGTH=None)
def test_a_setting_of_none_bounds_no_array() -> None:
    assert check_arguments(IDS, {"ids": list(range(1001))}) == {"ids": list(range(1001))}


@override_settings(SERVICE_SPECS_MAX_ARRAY_LENGTH=3)
def test_the_default_maximum_reaches_an_array_inside_a_row() -> None:
    rows = one(Parameter("books", "array", items=Parameters.of(Parameter("tags", "array"))))
    assert refusal(rows, {"books": [{"tags": [1, 2, 3, 4]}]}) == {
        "books": {0: {"tags": [TOO_MANY % 3]}}
    }


@override_settings(SERVICE_SPECS_MAX_ARRAY_LENGTH=3)
def test_a_declared_maximum_outranks_the_default_both_ways() -> None:
    wider = one(Parameter("ids", "array", max_length=5))
    narrower = one(Parameter("ids", "array", max_length=2))
    assert check_arguments(wider, {"ids": [1, 2, 3, 4, 5]}) == {"ids": [1, 2, 3, 4, 5]}
    assert refusal(wider, {"ids": [1, 2, 3, 4, 5, 6]}) == {"ids": [TOO_MANY % 5]}
    assert refusal(narrower, {"ids": [1, 2, 3]}) == {"ids": [TOO_MANY % 2]}


def test_a_declared_minimum_is_inclusive() -> None:
    params = one(Parameter("ids", "array", min_length=2))
    assert check_arguments(params, {"ids": [1, 2]}) == {"ids": [1, 2]}
    assert refusal(params, {"ids": [1]}) == {"ids": [TOO_FEW % 2]}
    assert refusal(params, {"ids": []}) == {"ids": [TOO_FEW % 2]}


@override_settings(SERVICE_SPECS_MAX_ARRAY_LENGTH=3)
def test_a_minimum_past_the_default_maximum_with_no_maximum_of_its_own_is_refused_loudly() -> None:
    # No call could pass, and the setting is read only at the call, so this is
    # where the declaration is found wrong rather than every call refused.
    params = one(Parameter("ids", "array", min_length=4))
    with pytest.raises(ImproperlyConfigured, match="min_length 4 is past the default maximum 3"):
        check_arguments(params, {"ids": [1, 2, 3, 4]})


@override_settings(SERVICE_SPECS_MAX_ARRAY_LENGTH=3)
def test_a_minimum_at_the_default_maximum_is_met_by_a_list_of_exactly_that_many() -> None:
    # The default bounds inclusively, so a minimum equal to it is meetable:
    # only one past it is refused as a declaration no call could pass.
    params = one(Parameter("ids", "array", min_length=3))
    assert check_arguments(params, {"ids": [1, 2, 3]}) == {"ids": [1, 2, 3]}
    assert refusal(params, {"ids": [1, 2]}) == {"ids": [TOO_FEW % 3]}
    assert refusal(params, {"ids": [1, 2, 3, 4]}) == {"ids": [TOO_MANY % 3]}


@override_settings(SERVICE_SPECS_MAX_ARRAY_LENGTH=3)
def test_a_minimum_past_the_default_is_taken_beside_its_own_maximum() -> None:
    params = one(Parameter("ids", "array", min_length=4, max_length=4))
    assert check_arguments(params, {"ids": [1, 2, 3, 4]}) == {"ids": [1, 2, 3, 4]}


def test_a_length_message_is_spelled_as_drf_spells_it() -> None:
    # No Django catalog entry counts a list's elements (MaxLengthValidator
    # counts characters), so the wording is DRF's ListField's, which its own
    # catalog translates wherever DRF is installed and which a
    # djangorestframework-services caller already reads.
    params = one(Parameter("ids", "array", min_length=1, max_length=1))
    assert refusal(params, {"ids": []}) == {"ids": ["Ensure this field has at least 1 elements."]}
    assert refusal(params, {"ids": [1, 2]}) == {
        "ids": ["Ensure this field has no more than 1 elements."]
    }


# --- messages ----------------------------------------------------------------------------------------


def test_messages_are_translated_when_raised_through_djangos_own_catalog() -> None:
    params = one(Parameter("pk", "integer", required=True))
    with translation.override("de"):
        detail = refusal(params, {})
        expected = translation.gettext(REQUIRED)
    assert expected != REQUIRED
    assert detail == {"pk": [expected]}
    # Translated now, not a lazy proxy, which is no ``str``: the message is a
    # ``CodedMessage``, so a ``str`` holding the translated words.
    assert all(isinstance(message, str) for message in detail["pk"])


class TestAny:
    @pytest.mark.parametrize(
        "value",
        [3, "abc", "3", 2.5, True, [1, "a"], {"a": [1]}, ""],
        ids=["int", "string", "numeric-string", "float", "bool", "list", "dict", "blank"],
    )
    def test_any_value_is_handed_on_unchanged(self, value: Any) -> None:
        params = Parameters.of(Parameter("pk", "any", required=True))

        cleaned = check_arguments(params, {"pk": value})

        # No coercion: a numeric string stays the string, a float stays a float.
        assert cleaned == {"pk": value}
        assert type(cleaned["pk"]) is type(value)

    def test_a_python_callers_value_of_no_json_type_is_handed_on_too(self) -> None:
        # No type is declared, so nothing is checked against one: a Django
        # ``File`` a multipart part carries under the name is handed on as well.
        upload = ContentFile(b"x", name="x.txt")

        assert check_arguments(Parameters.of(Parameter("pk", "any")), {"pk": upload}) == {
            "pk": upload
        }

    def test_null_is_refused_unless_nullable(self) -> None:
        strict = Parameters.of(Parameter("pk", "any"))
        loose = Parameters.of(Parameter("pk", "any", nullable=True))

        with pytest.raises(InvalidArguments) as refused:
            check_arguments(strict, {"pk": None})
        assert refused.value.detail == {"pk": ["This field cannot be null."]}
        assert check_arguments(loose, {"pk": None}) == {"pk": None}

    def test_a_required_any_is_refused_when_absent(self) -> None:
        with pytest.raises(InvalidArguments) as refused:
            check_arguments(Parameters.of(Parameter("pk", "any", required=True)), {})
        assert refused.value.detail == {"pk": ["This field is required."]}

    def test_nan_is_no_json_value_and_is_refused(self) -> None:
        with pytest.raises(InvalidArguments) as refused:
            check_arguments(Parameters.of(Parameter("pk", "any")), {"pk": float("nan")})
        assert refused.value.detail == {"pk": ["Enter a number."]}


@override_settings(SERVICE_SPECS_MAX_ARRAY_LENGTH=None)
def test_a_minimum_is_compared_with_no_default_when_the_setting_is_none() -> None:
    params = one(Parameter("ids", "array", min_length=2))
    assert check_arguments(params, {"ids": [1, 2]}) == {"ids": [1, 2]}
    assert refusal(params, {"ids": [1]}) == {"ids": [TOO_FEW % 2]}


# --- the code each refusal carries -------------------------------------------------

PRICE = Parameter("price", "string", format="decimal")


@pytest.mark.parametrize(
    ("parameter", "arguments", "expected"),
    [
        pytest.param(
            Parameter("title", "string", required=True),
            {},
            {"title": [(REQUIRED, "required")]},
            id="required",
        ),
        pytest.param(
            Parameter("title", "string"),
            {"title": None},
            {"title": [(NULL, "null")]},
            id="null",
        ),
        pytest.param(
            Parameter("title", "string"),
            {"colour": "red"},
            {"colour": [(UNKNOWN, "unknown")]},
            id="unknown",
        ),
        pytest.param(
            Parameter("title", "string"),
            {"title": 3},
            {"title": [("Expected a string.", "invalid")]},
            id="type",
        ),
        pytest.param(
            Parameter("ids", "array"),
            {"ids": "1"},
            {"ids": [("Expected an array.", "not_a_list")]},
            id="not-a-list",
        ),
        pytest.param(
            Parameter("author", "object"),
            {"author": 3},
            {"author": [("Expected an object.", "invalid")]},
            id="not-an-object",
        ),
        pytest.param(
            Parameter("books", "array", items=BOOK),
            {"books": ["Dune"]},
            {"books": {0: {NON_FIELD_ERRORS: [("Expected an object.", "invalid")]}}},
            id="row-not-an-object",
        ),
        pytest.param(
            PRICE,
            {"price": True},
            {"price": [("Expected a decimal string or a number.", "invalid")]},
            id="decimal-type",
        ),
        pytest.param(
            PRICE,
            {"price": "NaN"},
            {"price": [(NOT_A_NUMBER, "invalid")]},
            id="decimal-not-finite",
        ),
        pytest.param(
            Parameter("n", "number"),
            {"n": float("inf")},
            {"n": [(NOT_A_NUMBER, "invalid")]},
            id="number-not-finite",
        ),
        pytest.param(
            Parameter("at", "string", format="date-time"),
            {"at": "soon"},
            {"at": [("Enter a valid date/time.", "invalid")]},
            id="date-time",
        ),
        pytest.param(
            Parameter("on", "string", format="date"),
            {"on": "soon"},
            {"on": [("Enter a valid date.", "invalid")]},
            id="date",
        ),
        pytest.param(
            Parameter("n", "integer", maximum=5),
            {"n": 6},
            {"n": [("Ensure this value is less than or equal to 5.", "max_value")]},
            id="max-value",
        ),
        pytest.param(
            Parameter("n", "integer", minimum=1),
            {"n": 0},
            {"n": [("Ensure this value is greater than or equal to 1.", "min_value")]},
            id="min-value",
        ),
        pytest.param(
            Parameter("c", "string", choices=("a", "b")),
            {"c": "z"},
            {
                "c": [
                    (
                        "Select a valid choice. z is not one of the available choices.",
                        "invalid_choice",
                    )
                ]
            },
            id="choice",
        ),
        pytest.param(
            Parameter("ids", "array", max_length=1),
            {"ids": [1, 2]},
            {"ids": [("Ensure this field has no more than 1 elements.", "max_length")]},
            id="max-length",
        ),
        pytest.param(
            Parameter("ids", "array", min_length=2),
            {"ids": [1]},
            {"ids": [("Ensure this field has at least 2 elements.", "min_length")]},
            id="min-length",
        ),
        pytest.param(
            Parameter("scan", "file"),
            {"scan": "scan.pdf"},
            {"scan": [("Expected a file.", "invalid")]},
            id="file",
        ),
    ],
)
def test_each_refusal_carries_the_code_a_drf_field_gives_the_same_mistake(
    parameter: Parameter, arguments: dict[str, Any], expected: dict[Any, Any]
) -> None:
    assert coded(refusal(one(parameter), arguments)) == expected


def test_arguments_that_are_no_mapping_are_refused_as_a_serializer_refuses_them() -> None:
    assert coded(refusal(AUTHOR, ["Ursula"])) == {
        NON_FIELD_ERRORS: [("Expected an object.", "invalid")]
    }


def test_a_coded_refusal_is_its_plain_message_to_everything_but_its_code() -> None:
    detail = refusal(AUTHOR, {"name": "Ursula", "books": [{"title": None}]})
    # Equal to, and serialized as, the plain strings a tree without codes holds,
    # so the wire a transport writes is unchanged by them.
    assert detail == {"books": {0: {"title": [NULL]}}}
    assert json.dumps(detail) == json.dumps({"books": {0: {"title": [NULL]}}})
    assert NULL in {detail["books"][0]["title"][0]}
