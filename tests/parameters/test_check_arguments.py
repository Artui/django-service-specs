from __future__ import annotations

from decimal import Decimal
from types import MappingProxyType
from typing import Any

import pytest
from django.utils import translation

from django_service_specs.parameters.check_arguments import check_arguments
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.parameters.utils import NON_FIELD_ERRORS
from django_service_specs.validation.unknown_arguments import UnknownArguments

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
        ("integer", True, "Expected integer, got boolean."),
        ("number", False, "Expected number, got boolean."),
        ("integer", 1.5, "Expected integer, got number."),
        ("integer", "3", "Expected integer, got string."),
        ("string", 3, "Expected string, got integer."),
        ("boolean", "true", "Expected boolean, got string."),
        ("boolean", 1, "Expected boolean, got integer."),
        ("array", "a,b", "Expected array, got string."),
        ("array", {"a": 1}, "Expected array, got object."),
        ("object", ["a"], "Expected object, got array."),
        ("integer", Decimal("3"), "Expected integer, got Decimal."),
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


def test_a_tuple_comes_back_as_a_list() -> None:
    assert check_arguments(one(Parameter("x", "array")), {"x": ("a", "b")}) == {"x": ["a", "b"]}


def test_a_free_form_object_is_passed_through_as_the_callers() -> None:
    # Nothing is declared inside it, so nothing inside it is checked or closed.
    value = {"anything": {"at": ["all"]}}
    assert check_arguments(one(Parameter("x", "object")), {"x": value})["x"] is value


# --- format -----------------------------------------------------------------------------

DECIMAL = one(Parameter("price", "string", format="decimal"))


@pytest.mark.parametrize("value", ["9.99", " 9.99 ", "-1e3", 3, 2.5])
def test_a_decimal_accepts_a_string_or_a_json_number(value: Any) -> None:
    assert check_arguments(DECIMAL, {"price": value}) == {"price": value}


@pytest.mark.parametrize(("value", "actual"), [(True, "boolean"), (["9.99"], "array")])
def test_a_decimal_refuses_what_is_neither_a_string_nor_a_number(value: Any, actual: str) -> None:
    # A boolean would parse - Decimal(True) is 1 - so the type message, not the
    # parse message, is what proves the type check answered.
    message = f"Expected a decimal string or number, got {actual}."
    assert refusal(DECIMAL, {"price": value}) == {"price": [message]}


@pytest.mark.parametrize("value", ["abc", "", "NaN", "Infinity", "-inf"])
def test_a_decimal_string_must_parse_to_a_finite_number(value: str) -> None:
    assert refusal(DECIMAL, {"price": value}) == {"price": [NOT_A_NUMBER]}


def test_a_decimal_float_must_be_finite() -> None:
    assert refusal(DECIMAL, {"price": float("nan")}) == {"price": [NOT_A_NUMBER]}


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
    assert refusal(DATE, {"on": 20240131}) == {"on": ["Expected string, got integer."]}


# --- choices ---------------------------------------------------------------------------

STATUS = one(Parameter("status", "string", choices=("draft", "published")))


def test_a_value_of_the_right_type_outside_the_choices_is_refused() -> None:
    assert refusal(STATUS, {"status": "archived"}) == {
        "status": ["Value 'archived' is not a valid choice."]
    }


def test_a_value_among_the_choices_is_accepted() -> None:
    assert check_arguments(STATUS, {"status": "draft"}) == {"status": "draft"}


def test_the_type_check_answers_before_the_choices() -> None:
    # True == 1 in Python, so ``True in (1, 2)`` holds and only the type check
    # stands between a boolean and an integer choice.
    params = one(Parameter("rank", "integer", choices=(1, 2)))
    detail = refusal(params, {"rank": True})
    assert detail == {"rank": ["Expected integer, got boolean."]}
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
    assert refusal(params, {"ids": [1, "2", 3, True, None]}) == {
        "ids": {
            1: ["Expected integer, got string."],
            3: ["Expected integer, got boolean."],
            4: ["Expected integer, got null."],
        }
    }


def test_an_arrays_choices_constrain_each_element() -> None:
    params = one(Parameter("tags", "array", items="string", choices=("a", "b")))
    assert check_arguments(params, {"tags": ["b", "a"]}) == {"tags": ["b", "a"]}
    assert refusal(params, {"tags": ["a", "c"]}) == {
        "tags": {1: ["Value 'c' is not a valid choice."]}
    }


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
            0: {NON_FIELD_ERRORS: ["Expected object, got string."]},
            1: {NON_FIELD_ERRORS: ["Expected object, got null."]},
        }
    }


def test_an_object_inside_a_row_is_checked_two_levels_down() -> None:
    books = [
        {"title": "Lathe", "publisher": "Scribner"},
        {"title": "Dispossessed", "publisher": {}},
        {"title": "Earthsea", "publisher": {"name": "Parnassus"}},
    ]
    assert refusal(AUTHOR, {"name": "Le Guin", "books": books}) == {
        "books": {
            0: {"publisher": ["Expected object, got string."]},
            1: {"publisher": {"name": [REQUIRED]}},
        }
    }


def test_an_object_parameter_given_a_non_mapping_is_a_type_error_at_the_field() -> None:
    params = one(Parameter("publisher", "object", fields=PUBLISHER))
    assert refusal(params, {"publisher": ["Scribner"]}) == {
        "publisher": ["Expected object, got array."]
    }


def test_arguments_that_are_not_a_mapping_are_refused_at_the_root() -> None:
    assert refusal(AUTHOR, ["Le Guin"]) == {NON_FIELD_ERRORS: ["Expected object, got array."]}


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
        "name": ["Expected string, got integer."]
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
            0: {"title": ["Expected string, got integer."]},
            2: {"publisher": {"name": [NULL]}, "tenant": [UNKNOWN]},
            3: {NON_FIELD_ERRORS: ["Expected object, got integer."]},
        },
    }


# --- messages ----------------------------------------------------------------------------------------


def test_messages_are_translated_when_raised_through_djangos_own_catalog() -> None:
    params = one(Parameter("pk", "integer", required=True))
    with translation.override("de"):
        detail = refusal(params, {})
        expected = translation.gettext(REQUIRED)
    assert expected != REQUIRED
    assert detail == {"pk": [expected]}
    assert all(type(message) is str for message in detail["pk"])
