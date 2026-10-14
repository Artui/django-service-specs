from __future__ import annotations

import sys
from typing import Any

import pytest
from django import forms

from django_service_specs.parameters.check_arguments import check_arguments
from django_service_specs.parameters.coerce_flat import coerce_flat
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameters import Parameter, Parameters
from tests.parameters.utils import coded

NESTED = "This argument has nested parameters, which a flat transport cannot send."

FLAT = Parameters.of(
    Parameter("count", "integer"),
    Parameter("ratio", "number"),
    Parameter("active", "boolean"),
    Parameter("title", "string"),
    Parameter("price", "string", format="decimal"),
    Parameter("at", "string", format="date-time"),
    Parameter("on", "string", format="date"),
    Parameter("ids", "array", items="integer"),
    Parameter("flags", "array", items="boolean"),
    Parameter("tags", "array"),
    Parameter("meta", "object"),
)
BOOK = Parameters.of(Parameter("title", "string", required=True))


def refusal(parameters: Parameters, raw: dict[str, Any]) -> dict[Any, Any]:
    with pytest.raises(InvalidArguments) as caught:
        coerce_flat(parameters, raw)
    return caught.value.detail


def test_parses_integers_numbers_and_booleans() -> None:
    raw = {"count": "3", "ratio": "2.5", "active": "TRUE", "title": "Lathe"}
    assert coerce_flat(FLAT, raw) == {"count": 3, "ratio": 2.5, "active": True, "title": "Lathe"}


@pytest.mark.parametrize(
    ("value", "number"),
    [("3", 3), (str(2**53 + 1), 2**53 + 1), ("-12", -12), ("3.0", 3.0), ("1e3", 1000.0)],
)
def test_a_number_is_what_a_json_decoder_makes_of_the_same_digits(
    value: str, number: float
) -> None:
    # An integer literal decodes to an exact ``int`` and anything with a point
    # or an exponent to a ``float``, so the flat ``"3"`` reaches the Validator
    # as the JSON ``3`` does. Read through ``float``, 2**53 + 1 was 2**53.
    coerced = coerce_flat(FLAT, {"ratio": value})["ratio"]
    assert coerced == number
    assert type(coerced) is type(number)


# Digits past ``int``'s limit of 4300, which Python enforces from 3.10.7 on.
# Padded with zeros, ``float`` still reads the value as a finite number.
PADDED = "0" * 4300 + str(2**53 + 1)
LIMITED = getattr(sys, "get_int_max_str_digits", lambda: 0)() != 0


def test_an_integer_literal_past_int_s_digit_limit_is_refused_never_rounded() -> None:
    # Digits alone spell an integer, so where ``int`` refuses them they spell
    # no number at all, rather than the float neighbour 2**53 that
    # ``float`` makes of them. A Python with no digit limit reads them exactly.
    if LIMITED:
        assert refusal(FLAT, {"ratio": PADDED}) == {"ratio": ["Enter a number."]}
    else:
        assert coerce_flat(FLAT, {"ratio": PADDED}) == {"ratio": 2**53 + 1}
    long = "9" * 4301
    assert refusal(FLAT, {"ratio": long}) == {"ratio": ["Enter a number."]}
    assert refusal(FLAT, {"count": long}) == {"count": ["Enter a whole number."]}


@pytest.mark.parametrize(
    ("spelling", "value"),
    [("true", True), ("True", True), ("1", True), ("false", False), ("FALSE", False), ("0", False)],
)
def test_a_boolean_has_exactly_four_spellings_in_any_case(spelling: str, value: bool) -> None:
    assert coerce_flat(FLAT, {"active": spelling}) == {"active": value}


@pytest.mark.parametrize("spelling", ["no", "off", "n", "yes", "", "2"])
def test_every_other_boolean_spelling_is_refused(spelling: str) -> None:
    assert refusal(FLAT, {"active": spelling}) == {"active": ["Enter true, false, 1 or 0."]}


@pytest.mark.parametrize("value", ["3.5", "5.05", "three", "", ".0", "5.0.0", "1e3"])
def test_an_integer_must_be_a_whole_number(value: str) -> None:
    # ``.0`` and ``5.0.0`` lose their trailing zeros and still do not parse,
    # as in Django's IntegerField; ``1e3`` is no decimal spelling at all.
    assert refusal(FLAT, {"count": value}) == {"count": ["Enter a whole number."]}


@pytest.mark.parametrize(
    ("value", "number"), [("5.0", 5), ("5.", 5), ("-3.000", -3), (" 7.0 ", 7), ("0.0", 0)]
)
def test_an_integral_decimal_spelling_is_an_integer(value: str, number: int) -> None:
    # Django's IntegerField strips ``.0*`` and trailing space before ``int``,
    # and so does DRF's, so both read each of these as a whole number. The
    # field itself is asked, so the two readings cannot drift apart unseen.
    coerced = coerce_flat(FLAT, {"count": value})
    assert coerced == {"count": number} == {"count": forms.IntegerField().clean(value)}
    assert type(coerced["count"]) is int


def test_an_arrays_integer_elements_read_an_integral_decimal_alike() -> None:
    # A repeated query-string key arrives as a list of strings, and each element
    # is read as the parameter of its ``items`` type would be.
    assert coerce_flat(FLAT, {"ids": ["5.0", "6.", "7"]}) == {"ids": [5, 6, 7]}
    assert refusal(FLAT, {"ids": ["5.0", "5.5"]}) == {"ids": {1: ["Enter a whole number."]}}


# Arabic-Indic five, fullwidth five, an Arabic-Indic five point zero, and a
# five behind a no-break space: Python's ``int`` and ``float`` read every one.
_NON_ASCII_NUMBERS = ["\u0665", "\uff15", "\u0665.0", "\u00a05"]


@pytest.mark.parametrize("value", _NON_ASCII_NUMBERS)
def test_a_number_spelled_outside_ascii_is_refused(value: str) -> None:
    # Django's form fields read each of these as 5, and pydantic and JSON read
    # none of them; refused here, in each type's own words, so a query string
    # never hands a Validator a number its caller did not spell in digits.
    assert refusal(FLAT, {"count": value, "ratio": value}) == {
        "count": ["Enter a whole number."],
        "ratio": ["Enter a number."],
    }


@pytest.mark.parametrize("value", ["two", "nan", "inf", "-Infinity"])
def test_a_number_must_parse_to_a_finite_number(value: str) -> None:
    # NaN and the infinities parse as floats, and no JSON caller can send one.
    assert refusal(FLAT, {"ratio": value}) == {"ratio": ["Enter a number."]}


def test_a_decimal_a_date_time_and_a_date_stay_strings_for_the_validator() -> None:
    raw = {"price": "9.99", "at": "2024-01-31T10:00:00Z", "on": "2024-01-31"}
    assert coerce_flat(FLAT, raw) == raw


def test_an_array_coerces_each_element_and_wraps_a_single_value() -> None:
    assert coerce_flat(FLAT, {"ids": ["1", "2"], "flags": ("true", "0")}) == {
        "ids": [1, 2],
        "flags": [True, False],
    }
    assert coerce_flat(FLAT, {"ids": "7"}) == {"ids": [7]}


def test_an_array_with_no_items_keeps_its_strings() -> None:
    assert coerce_flat(FLAT, {"tags": ["a", "1"]}) == {"tags": ["a", "1"]}


def test_an_array_addresses_a_failing_element_by_index() -> None:
    assert refusal(FLAT, {"ids": ["1", "two", "3", "4.5"]}) == {
        "ids": {1: ["Enter a whole number."], 3: ["Enter a whole number."]}
    }


def test_none_is_not_wrapped_into_an_array() -> None:
    # Holds the ``value is None`` condition in ``coerce_flat``. An option
    # argparse never received is absent, not a list holding a null.
    assert coerce_flat(FLAT, {"ids": None}) == {"ids": None}


def test_a_value_that_is_not_a_string_passes_through() -> None:
    raw = {"count": 3, "active": False, "ids": [1, "2"], "meta": {"a": "1"}}
    assert coerce_flat(FLAT, raw) == {
        "count": 3,
        "active": False,
        "ids": [1, 2],
        "meta": {"a": "1"},
    }


def test_an_undeclared_key_passes_through_for_the_closed_set_to_refuse() -> None:
    assert coerce_flat(FLAT, {"tenant": "acme"}) == {"tenant": "acme"}


@pytest.mark.parametrize(
    "parameter",
    [
        Parameter("books", "array", items=BOOK),
        Parameter("author", "object", fields=BOOK),
    ],
)
def test_a_parameter_with_nested_parameters_is_refused_by_name(parameter: Parameter) -> None:
    detail = refusal(Parameters.of(parameter), {parameter.name: "Lathe"})
    assert detail == {parameter.name: [NESTED]}


def test_a_nested_parameter_is_refused_whatever_its_value() -> None:
    # A flat transport cannot have produced it, so there is no value to trust.
    books = Parameters.of(Parameter("books", "array", items=BOOK))
    assert refusal(books, {"books": [{"title": "Lathe"}]}) == {"books": [NESTED]}


def test_every_refusal_is_reported_at_once() -> None:
    params = FLAT + Parameters.of(Parameter("books", "array", items=BOOK))
    raw = {"count": "x", "active": "yes", "ids": ["1", "y"], "books": "z", "title": "ok"}
    assert refusal(params, raw) == {
        "count": ["Enter a whole number."],
        "active": ["Enter true, false, 1 or 0."],
        "ids": {1: ["Enter a whole number."]},
        "books": [NESTED],
    }


def test_argv_through_coerce_flat_reads_as_typed_json_to_the_shape_check() -> None:
    raw = {"count": "3", "ratio": "0.5", "active": "false", "ids": "4", "price": "9.99"}
    typed = {"count": 3, "ratio": 0.5, "active": False, "ids": [4], "price": "9.99"}
    assert check_arguments(FLAT, coerce_flat(FLAT, raw)) == check_arguments(FLAT, typed)


def test_an_any_parameter_keeps_the_string_it_arrived_as() -> None:
    # A query string's "3" stays "3": ``any`` names no type to read it as.
    params = Parameters.of(Parameter("pk", "any"), Parameter("on", "any"))

    assert coerce_flat(params, {"pk": "3", "on": "true"}) == {"pk": "3", "on": "true"}


def test_an_array_past_its_maximum_is_refused_whole_before_any_element_is_read() -> None:
    # Every element is malformed and none is addressed: the length is read
    # first, so a long flat list costs no per-element parse.
    ids = Parameters.of(Parameter("ids", "array", items="integer"))
    with pytest.raises(InvalidArguments) as refused:
        coerce_flat(ids, {"ids": ["x"] * 1001})
    assert refused.value.detail == {"ids": ["Ensure this field has no more than 1000 elements."]}
    assert "Enter a whole number." not in str(refused.value.detail)


def test_an_array_at_its_maximum_is_read_element_by_element() -> None:
    ids = Parameters.of(Parameter("ids", "array", items="integer"))
    assert coerce_flat(ids, {"ids": ["1"] * 1000}) == {"ids": [1] * 1000}


def test_each_refusal_carries_the_code_a_drf_field_gives_the_same_mistake() -> None:
    raw = {
        "count": "three",
        "ratio": "half",
        "active": "maybe",
        "ids": ["1", "x"],
        "author": "Ursula",
    }
    parameters = Parameters.of(*FLAT, Parameter("author", "object", fields=BOOK))
    assert coded(refusal(parameters, raw)) == {
        "count": [("Enter a whole number.", "invalid")],
        "ratio": [("Enter a number.", "invalid")],
        "active": [("Enter true, false, 1 or 0.", "invalid")],
        "ids": {1: [("Enter a whole number.", "invalid")]},
        # A nested serializer handed a string refuses it as ``invalid`` too.
        "author": [(NESTED, "invalid")],
    }


def test_a_list_past_its_maximum_carries_the_length_code() -> None:
    parameters = Parameters.of(Parameter("ids", "array", items="integer", max_length=1))
    assert coded(refusal(parameters, {"ids": ["1", "2"]})) == {
        "ids": [("Ensure this field has no more than 1 elements.", "max_length")]
    }
