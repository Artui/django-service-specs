from __future__ import annotations

from typing import Any

import pytest
from django import forms

from django_service_specs.parameters.check_arguments import check_arguments
from django_service_specs.parameters.coerce_flat import coerce_flat
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters

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


def test_a_json_number_is_a_float_even_when_it_is_whole() -> None:
    # What a JSON number decodes to is a float for a "number"; the shape check
    # accepts either, and this one keeps the reading to one spelling.
    assert coerce_flat(FLAT, {"ratio": "3"}) == {"ratio": 3.0}


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
