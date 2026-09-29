from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from django.utils import translation

from django_service_specs.adapters.dataclass.dataclass_validator import DataclassValidator
from django_service_specs.parameters.check_arguments import check_arguments
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.types.unset import UNSET, UnsetType
from django_service_specs.validation.validation_context import ValidationContext
from tests.adapter_app.models import Status
from tests.adapters.dataclass.utils import (
    Address,
    Booking,
    Colour,
    Computed,
    Everything,
    Line,
    Priority,
    Range,
    Schedule,
)

CONTEXT = ValidationContext(principal=None)

REQUIRED = "This field is required."


def _line(**overrides: Any) -> dict[str, Any]:
    return {"sku": "A-1", "quantity": 1, "ship_to": {"city": "Oslo"}, **overrides}


def _arguments(**overrides: Any) -> dict[str, Any]:
    """Arguments for ``Everything`` as a JSON wire would carry them."""
    return {
        "name": "Order",
        "count": 2,
        "ratio": 0.5,
        "active": True,
        "price": "12.50",
        "at": "2024-06-01T12:00:00+00:00",
        "on": "2024-06-01",
        "status": "draft",
        "priority": 2,
        "colour": "red",
        "mode": "fast",
        "tags": ["a", "b"],
        "address": {"city": "Oslo", "postcode": "0150"},
        "lines": [_line()],
        **overrides,
    }


def _refusal(cls: type[Any], arguments: dict[str, Any]) -> dict[Any, Any]:
    with pytest.raises(InvalidArguments) as caught:
        DataclassValidator(cls).validate(arguments, CONTEXT)
    return caught.value.detail


@dataclass
class _Price:
    price: Decimal


@dataclass
class _When:
    at: dt.datetime


@dataclass
class _Day:
    on: dt.date


@dataclass
class _Patch:
    # No default: UnsetType alone is what makes it optional.
    bio: str | None | UnsetType


@dataclass
class _Maybe:
    address: Address | None
    scores: list[int | None]


@dataclass
class _Defaults:
    price: Decimal = Decimal("9.99")
    colour: Colour = Colour.RED
    on: dt.date = dt.date(2024, 1, 1)
    address: Address | UnsetType = UNSET


@dataclass
class _Unmappable:
    blob: dict[str, int]


# --- construction ----------------------------------------------------------------


@pytest.mark.parametrize("cls", [dict, Address("Oslo")])
def test_refuses_anything_but_a_dataclass_type(cls: Any) -> None:
    with pytest.raises(ImproperlyConfigured, match="DataclassValidator takes a dataclass type"):
        DataclassValidator(cls)


def test_annotations_are_read_on_first_use_not_at_construction() -> None:
    validator = DataclassValidator(_Unmappable)
    with pytest.raises(ImproperlyConfigured, match="_Unmappable.blob"):
        validator.parameters()


# --- parameters() ---------------------------------------------------------------------


def test_parameters_map_every_supported_annotation() -> None:
    address = Parameters.of(
        Parameter("city", "string", required=True),
        Parameter("postcode", "string", nullable=True, default=None),
    )
    line = Parameters.of(
        Parameter("pk", "integer", nullable=True, default=None),
        Parameter("sku", "string", required=True),
        Parameter("quantity", "integer", required=True),
        Parameter("ship_to", "object", required=True, fields=address),
    )
    assert DataclassValidator(Everything).parameters() == Parameters.of(
        Parameter("name", "string", required=True),
        Parameter("count", "integer", required=True),
        Parameter("ratio", "number", required=True),
        Parameter("active", "boolean", required=True),
        Parameter("price", "string", required=True, format="decimal"),
        Parameter("at", "string", required=True, format="date-time"),
        Parameter("on", "string", required=True, format="date"),
        Parameter("status", "string", required=True, choices=("draft", "published")),
        Parameter("priority", "integer", required=True, choices=(1, 2)),
        Parameter("colour", "string", required=True, choices=("red", "blue")),
        Parameter("mode", "string", required=True, choices=("fast", "slow")),
        Parameter("tags", "array", required=True, items="string"),
        Parameter("address", "object", required=True, fields=address),
        Parameter("lines", "array", required=True, items=line),
        Parameter("note", "string", nullable=True, default=None),
        # UnsetType: optional, with no default a transport could print.
        Parameter("bio", "string", nullable=True),
        Parameter("level", "integer", default=3),
        # A factory's value is not a declaration, so no default is reported.
        Parameter("extras", "array", items="integer"),
    )


def test_a_default_is_reported_as_the_argument_that_would_send_it() -> None:
    parameters = DataclassValidator(_Defaults).parameters()
    assert [p.default for p in parameters] == ["9.99", "red", "2024-01-01", UNSET]
    assert not any(p.required for p in parameters)


def test_unset_type_alone_makes_a_field_optional() -> None:
    (bio,) = DataclassValidator(_Patch).parameters()
    assert (bio.required, bio.nullable, bio.default) == (False, True, UNSET)


def test_a_field_the_dataclass_computes_is_not_a_parameter() -> None:
    assert DataclassValidator(Computed).parameters().names() == {"base"}


# --- validate(): values -----------------------------------------------------------------


def test_validate_decodes_into_the_declared_types() -> None:
    values = DataclassValidator(Everything).validate(_arguments(), CONTEXT)
    assert values == {
        "name": "Order",
        "count": 2,
        "ratio": 0.5,
        "active": True,
        "price": Decimal("12.50"),
        "at": dt.datetime(2024, 6, 1, 12, tzinfo=dt.timezone.utc),
        "on": dt.date(2024, 6, 1),
        "status": Status.DRAFT,
        "priority": Priority.HIGH,
        "colour": Colour.RED,
        "mode": "fast",
        "tags": ["a", "b"],
        "address": Address("Oslo", "0150"),
        "lines": [Line(sku="A-1", quantity=1, ship_to=Address("Oslo"))],
        # Omitted: the dataclass fills its defaults, and UnsetType stays UNSET.
        "note": None,
        "bio": UNSET,
        "level": 3,
        "extras": [],
    }
    assert type(values["colour"]) is Colour
    assert type(values["status"]) is Status


def test_nested_values_are_dataclass_instances_two_levels_down() -> None:
    values = DataclassValidator(Everything).validate(_arguments(), CONTEXT)
    (line,) = values["lines"]
    assert isinstance(line, Line)
    assert isinstance(line.ship_to, Address)


def test_a_row_declaring_its_key_carries_it() -> None:
    values = DataclassValidator(Everything).validate(
        _arguments(lines=[_line(pk=7), _line()]), CONTEXT
    )
    assert [line.pk for line in values["lines"]] == [7, None]


def test_a_number_takes_an_integer_and_holds_a_float() -> None:
    values = DataclassValidator(Everything).validate(_arguments(ratio=2), CONTEXT)
    assert values["ratio"] == 2.0
    assert type(values["ratio"]) is float


@pytest.mark.parametrize(
    ("argument", "expected"),
    [("3.10", Decimal("3.10")), (3, Decimal("3")), (0.1, Decimal("0.1"))],
)
def test_a_decimal_takes_a_string_or_a_json_number(argument: Any, expected: Decimal) -> None:
    values = DataclassValidator(_Price).validate({"price": argument}, CONTEXT)
    assert values["price"] == expected
    # Equal is not enough: Decimal(0.1) == Decimal("0.1") is False, so this
    # also holds the float to the digits the wire carried.
    assert str(values["price"]) == str(expected)


def test_unset_type_with_no_default_is_filled_with_unset() -> None:
    assert DataclassValidator(_Patch).validate({}, CONTEXT) == {"bio": UNSET}
    assert DataclassValidator(_Patch).validate({"bio": None}, CONTEXT) == {"bio": None}


def test_nullable_objects_and_elements_take_null() -> None:
    values = DataclassValidator(_Maybe).validate({"address": None, "scores": [1, None]}, CONTEXT)
    assert values == {"address": None, "scores": [1, None]}


def test_a_computed_field_is_neither_taken_nor_returned() -> None:
    assert DataclassValidator(Computed).validate({"base": 2}, CONTEXT) == {"base": 2}
    detail = _refusal(Computed, {"base": 2, "doubled": 4})
    assert detail == {"doubled": ["Unknown argument."]}


# --- validate(): time zones -------------------------------------------------------------


@override_settings(TIME_ZONE="Europe/Paris")
def test_an_offset_less_date_time_is_made_aware_in_the_current_time_zone() -> None:
    # USE_TZ and naive: the one combination that converts.
    at = DataclassValidator(_When).validate({"at": "2024-06-01T12:00:00"}, CONTEXT)["at"]
    assert at.utcoffset() == dt.timedelta(hours=2)
    assert at == dt.datetime(2024, 6, 1, 10, tzinfo=dt.timezone.utc)


@override_settings(TIME_ZONE="Europe/Paris")
def test_a_date_time_with_an_offset_keeps_it() -> None:
    # USE_TZ and aware: nothing to convert, and the offset sent is the one kept.
    at = DataclassValidator(_When).validate({"at": "2024-06-01T12:00:00-05:00"}, CONTEXT)["at"]
    assert at.utcoffset() == dt.timedelta(hours=-5)


@override_settings(USE_TZ=False)
def test_without_use_tz_an_offset_less_date_time_stays_naive() -> None:
    at = DataclassValidator(_When).validate({"at": "2024-06-01T12:00:00"}, CONTEXT)["at"]
    assert at == dt.datetime(2024, 6, 1, 12)
    assert at.tzinfo is None


# --- validate(): refusals ------------------------------------------------------------------


def test_every_required_field_is_reported_not_the_first() -> None:
    detail = _refusal(Everything, {})
    required = {p.name for p in DataclassValidator(Everything).parameters() if p.required}
    assert detail == {name: [REQUIRED] for name in required}


@pytest.mark.parametrize(
    ("overrides", "detail"),
    [
        ({"name": 5}, {"name": ["Expected a string."]}),
        ({"count": "3"}, {"count": ["Expected an integer."]}),
        # bool subclasses int in Python and is not an integer on the wire.
        ({"count": True}, {"count": ["Expected an integer."]}),
        # A float is a number, not an integer, even when it is whole.
        ({"count": 2.0}, {"count": ["Expected an integer."]}),
        ({"ratio": "0.5"}, {"ratio": ["Expected a number."]}),
        ({"active": 1}, {"active": ["Expected a boolean."]}),
        ({"count": None}, {"count": ["This field cannot be null."]}),
        ({"tags": "a"}, {"tags": ["Expected an array."]}),
        ({"address": "Oslo"}, {"address": ["Expected an object."]}),
        ({"address": None}, {"address": ["This field cannot be null."]}),
        ({"tenant": "acme"}, {"tenant": ["Unknown argument."]}),
    ],
)
def test_a_wrong_json_type_is_refused_not_a_crash(overrides: dict, detail: dict) -> None:
    assert _refusal(Everything, _arguments(**overrides)) == detail


@pytest.mark.parametrize(
    ("overrides", "detail"),
    [
        (
            {"status": "archived"},
            {"status": ["Select a valid choice. archived is not one of the available choices."]},
        ),
        (
            {"colour": "green"},
            {"colour": ["Select a valid choice. green is not one of the available choices."]},
        ),
        (
            {"mode": "idle"},
            {"mode": ["Select a valid choice. idle is not one of the available choices."]},
        ),
        # The JSON type is checked before membership: ``True == 1`` in Python,
        # so ``true`` would otherwise pass as the integer choice 1.
        ({"priority": True}, {"priority": ["Expected an integer."]}),
        ({"mode": 1}, {"mode": ["Expected a string."]}),
    ],
)
def test_a_value_outside_the_choices_is_refused(overrides: dict, detail: dict) -> None:
    assert _refusal(Everything, _arguments(**overrides)) == detail


@pytest.mark.parametrize(
    "argument",
    [
        # A Decimal is the case only the JSON type check answers: its str
        # parses, so without the check a value no wire carries would pass,
        # where a date-time object is refused for not being a string.
        Decimal("1.5"),
        True,
        [1],
    ],
)
def test_a_decimal_that_is_neither_a_string_nor_a_number_is_refused(argument: Any) -> None:
    # The type check's own message, which the parse below never produces, so
    # this names the check that answered.
    assert _refusal(_Price, {"price": argument}) == {
        "price": ["Expected a decimal string or a number."]
    }


@pytest.mark.parametrize("argument", ["twelve", "NaN", "Infinity"])
def test_a_decimal_that_is_not_a_finite_number_is_refused(argument: Any) -> None:
    assert _refusal(_Price, {"price": argument}) == {"price": ["Enter a number."]}


@pytest.mark.parametrize(
    "argument",
    [
        1717243200,  # not a string
        "next tuesday",  # a string Django's parser returns None for
        "2024-02-30T10:00:00",  # well formed, and not a day: the parser raises
    ],
)
def test_a_date_time_django_cannot_parse_is_refused(argument: Any) -> None:
    assert _refusal(_When, {"at": argument}) == {"at": ["Enter a valid date/time."]}


@pytest.mark.parametrize("argument", [20240601, "June", "2024-02-30"])
def test_a_date_django_cannot_parse_is_refused(argument: Any) -> None:
    assert _refusal(_Day, {"on": argument}) == {"on": ["Enter a valid date."]}


def test_a_scalar_element_is_refused_at_its_index() -> None:
    detail = _refusal(Everything, _arguments(tags=["a", 1, "c", None]))
    assert detail == {
        "tags": {1: ["Expected a string."], 3: ["This field cannot be null."]},
    }


def test_bad_rows_are_refused_by_index_and_only_the_rows_that_failed() -> None:
    lines = [
        _line(),
        _line(quantity="two", tenant="acme"),
        "A-3",
        None,
        _line(ship_to={"postcode": 150}),
    ]
    detail = _refusal(Everything, _arguments(lines=lines))
    assert detail == {
        "lines": {
            1: {"quantity": ["Expected an integer."], "tenant": ["Unknown argument."]},
            # A message about a row itself sits inside the row.
            2: {"non_field_errors": ["Expected an object."]},
            3: {"non_field_errors": ["This field cannot be null."]},
            # Two levels down: a row containing an object.
            4: {"ship_to": {"city": [REQUIRED], "postcode": ["Expected a string."]}},
        }
    }


def test_the_tree_holds_int_row_keys_and_str_messages() -> None:
    detail = _refusal(Everything, _arguments(name=None, lines=[_line(), _line(sku=1)]))
    (row,) = detail["lines"]
    assert type(row) is int
    assert all(type(message) is str for message in detail["name"])


def test_every_failure_is_collected_across_levels() -> None:
    detail = _refusal(Everything, _arguments(count="x", address={}, lines=[{}]))
    assert set(detail) == {"count", "address", "lines"}
    assert detail["lines"][0] == {
        "sku": [REQUIRED],
        "quantity": [REQUIRED],
        "ship_to": [REQUIRED],
    }


def test_post_init_value_error_is_a_message_about_that_object() -> None:
    assert _refusal(Range, {"start": 5, "end": 1}) == {
        "non_field_errors": ["The range ends before it starts."]
    }


def test_post_init_value_error_in_a_row_lands_inside_the_row() -> None:
    ranges = [{"start": 1, "end": 2}, {"start": 5, "end": 1}]
    assert _refusal(Schedule, {"ranges": ranges}) == {
        "ranges": {1: {"non_field_errors": ["The range ends before it starts."]}}
    }


def test_post_init_django_validation_error_is_a_message_about_that_object() -> None:
    assert _refusal(Booking, {"nights": 40}) == {
        "non_field_errors": ["A booking is at most 30 nights."]
    }


def test_messages_are_translated_when_raised() -> None:
    with translation.override("fr"):
        detail = _refusal(_Price, {})
    assert detail == {"price": ["Ce champ est obligatoire."]}


@dataclass
class _Typed:
    count: int
    price: Decimal
    status: Status


@pytest.mark.parametrize(
    "arguments",
    [{"count": "3"}, {"price": True}, {"status": "archived"}],
    ids=["type", "decimal", "choice"],
)
def test_the_validator_and_the_shape_check_refuse_a_fault_in_the_same_words(
    arguments: dict[str, Any],
) -> None:
    # Dispatch puts the shape check in front of the Validator, so a caller of
    # dispatch only ever reads the first; a caller of ``validate()`` reads the
    # second. One fault should read the same to both.
    valid = {"count": 1, "price": "1.5", "status": Status.values[0]}
    validator = DataclassValidator(_Typed)
    with pytest.raises(InvalidArguments) as shape:
        check_arguments(validator.parameters(), {**valid, **arguments})
    assert shape.value.detail == _refusal(_Typed, {**valid, **arguments})


@dataclass
class _Tagged:
    modes: list[Literal["fast", "slow"]]
    colours: list[Colour]
    statuses: list[Status]


def test_a_list_of_choices_declares_them_for_each_element() -> None:
    # ``items`` holds only the element's JSON type, and an array's choices
    # constrain each element, so a list of choices keeps them there: where the
    # shape check and the JSON Schema read them.
    params = DataclassValidator(_Tagged).parameters()
    assert [(p.name, p.items, p.choices) for p in params] == [
        ("modes", "string", ("fast", "slow")),
        ("colours", "string", ("red", "blue")),
        ("statuses", "string", ("draft", "published")),
    ]


@dataclass
class _Gaps:
    scores: list[int | None]
    addresses: list[Address | None]
    modes: list[Literal["fast", None]]
    tags: list[str]


def test_a_nullable_element_is_declared_on_the_array_and_not_as_the_array() -> None:
    params = DataclassValidator(_Gaps).parameters()
    assert [(p.name, p.items_nullable, p.nullable) for p in params] == [
        ("scores", True, False),
        ("addresses", True, False),
        # ``Literal["fast", None]`` spells a nullable choice: the null is the
        # element's to take, and the choices keep only the values.
        ("modes", True, False),
        ("tags", False, False),
    ]
    modes = params.get("modes")
    assert modes is not None and modes.choices == ("fast",)


def test_the_shape_check_passes_the_null_elements_the_validator_takes() -> None:
    # Dispatch runs the shape check before the Validator, so a null element the
    # declaration did not call nullable was refused before this adapter saw it.
    params = DataclassValidator(_Gaps).parameters()
    arguments = {
        "scores": [1, None],
        "addresses": [None, {"city": "Oslo"}],
        "modes": [None, "fast"],
        "tags": ["a"],
    }
    values = DataclassValidator(_Gaps).validate(check_arguments(params, arguments), CONTEXT)
    assert values == {
        "scores": [1, None],
        "addresses": [None, Address(city="Oslo")],
        "modes": [None, "fast"],
        "tags": ["a"],
    }
    with pytest.raises(InvalidArguments) as caught:
        check_arguments(params, {**arguments, "tags": [None]})
    assert caught.value.detail == {"tags": {0: ["Expected a string."]}}
