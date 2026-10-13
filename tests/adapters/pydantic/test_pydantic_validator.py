from __future__ import annotations

import datetime as dt
import enum
import math
import re
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace
from typing import Annotated, Any, Literal

import pytest
from annotated_types import Len, MaxLen, MinLen
from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    computed_field,
    conlist,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from django_service_specs.adapters.dataclass.dataclass_validator import DataclassValidator
from django_service_specs.adapters.forms.form_validator import FormValidator
from django_service_specs.adapters.pydantic.pydantic_validator import PydanticValidator
from django_service_specs.http.request_arguments import request_arguments
from django_service_specs.mutations.create_from_input import create_from_input
from django_service_specs.parameters.check_arguments import check_arguments
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.parameters.utils import NON_FIELD_ERRORS
from django_service_specs.relations.child_spec import ChildSpec
from django_service_specs.schema.parameters_schema import parameters_schema
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.validation.validation_context import ValidationContext
from tests.adapter_app.models import Author, Book, Status
from tests.adapters.dataclass import utils as dataclass_models
from tests.adapters.pydantic.utils import (
    Address,
    Colour,
    Everything,
    Line,
    Node,
    Priority,
    Range,
    Schedule,
)
from tests.parameters.utils import coded

CONTEXT = ValidationContext(principal=None)

RANGE_REFUSED = "Value error, The range ends before it starts."


class _Wire(BaseModel):
    first_name: str = Field(alias="firstName")
    note: str | None = Field(None, validation_alias="memo")


class _ByName(BaseModel):
    model_config = ConfigDict(validate_by_alias=False, validate_by_name=True)
    first_name: str = Field(alias="firstName")


class _Located(BaseModel):
    # pydantic locates an error by field name here, not by the key it validated.
    model_config = ConfigDict(loc_by_alias=False)
    first_name: int = Field(alias="firstName")


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str


class _Scores(BaseModel):
    scores: dict[str, int]


class _Labels(BaseModel):
    labels: dict[str, str]


class _Bounded(BaseModel):
    name: str = Field(max_length=3)


class _Titled(BaseModel):
    title: str = Field(description="What the row is called.")

    @field_validator("title")
    @classmethod
    def _not_the_current_title(cls, value: str, info: ValidationInfo) -> str:
        # The kernel's context, as pydantic hands it to every validator.
        context = info.context
        if value == context["target"].title:
            raise ValueError(f"{context['principal']} gave it that title already.")
        return value


class _Computed(BaseModel):
    base: int

    @computed_field
    @property
    def doubled(self) -> int:
        return self.base * 2


class _Unmappable(BaseModel):
    blob: set[int]


class _Span(BaseModel):
    start: int
    end: int
    inner: _Span | None = None

    @model_validator(mode="after")
    def _ordered(self) -> _Span:
        if self.end < self.start:
            raise ValueError("The span ends before it starts.")
        return self


class _BookIn(BaseModel):
    pk: int | None = None
    title: str
    price: Decimal
    status: Status = Status.DRAFT


class _AuthorIn(BaseModel):
    name: str
    books: list[_BookIn] = []


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


def _refusal(model: type[BaseModel], arguments: dict[str, Any]) -> dict[Any, Any]:
    with pytest.raises(InvalidArguments) as caught:
        PydanticValidator(model).validate(arguments, CONTEXT)
    return caught.value.detail


def _tree(depth: int, leaf: dict[str, Any]) -> dict[str, Any]:
    """A ``Node`` payload ``depth`` levels deep, one child per level, ending in ``leaf``."""
    return leaf if depth == 1 else {"name": f"level {depth}", "children": [_tree(depth - 1, leaf)]}


class TestConstruction:
    @pytest.mark.parametrize("model", [dict, Address(city="Oslo")])
    def test_refuses_anything_but_a_model_class(self, model: Any) -> None:
        with pytest.raises(
            ImproperlyConfigured, match="PydanticValidator takes a pydantic model class"
        ):
            PydanticValidator(model)

    def test_the_declaration_is_read_at_construction(self) -> None:
        with pytest.raises(ImproperlyConfigured, match="_Unmappable.blob: set\\[int\\] has no"):
            PydanticValidator(_Unmappable)


class TestParameters:
    def test_a_model_declares_what_the_same_dataclass_declares(self) -> None:
        # Everything mirrors the dataclass tests' model field for field, less the
        # one annotation only the dataclass adapter reads (UnsetType), and the
        # dataclass adapter's own tests pin every one of those parameters.
        by_dataclass = DataclassValidator(dataclass_models.Everything).parameters()
        assert PydanticValidator(Everything).parameters() == Parameters(
            p for p in by_dataclass if p.name != "bio"
        )

    def test_every_parameter_is_one_the_shape_check_accepts(self) -> None:
        parameters = PydanticValidator(Everything).parameters()
        assert check_arguments(parameters, _arguments()) == _arguments()

    def test_a_computed_field_is_not_a_parameter(self) -> None:
        assert PydanticValidator(_Computed).parameters().names() == {"base"}

    def test_a_parameter_is_named_for_the_key_pydantic_validates_by(self) -> None:
        parameters = PydanticValidator(_Wire).parameters()
        assert [p.name for p in parameters] == ["firstName", "memo"]

    def test_a_model_validating_by_field_name_takes_the_names_it_declares(self) -> None:
        # The declaration and the model must agree on the key: a parameter
        # pydantic would not accept is one no caller can send.
        validator = PydanticValidator(_ByName)
        assert [p.name for p in validator.parameters()] == ["first_name"]
        assert validator.validate({"first_name": "Ada"}, CONTEXT) == {"first_name": "Ada"}

    def test_help_is_the_field_description(self) -> None:
        (title,) = PydanticValidator(_Titled).parameters()
        assert title.help == "What the row is called."

    def test_a_tree_is_declared_to_the_bound_then_as_rows_of_objects(self) -> None:
        children = PydanticValidator(Node).parameters().get("children")
        for _ in range(3):
            assert children is not None and isinstance(children.items, Parameters)
            children = children.items.get("children")
        assert children is not None
        assert (children.type, children.items) == ("array", "object")


class TestValidate:
    def test_values_are_built_into_the_declared_types(self) -> None:
        values = PydanticValidator(Everything).validate(_arguments(), CONTEXT)
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
            "address": Address(city="Oslo", postcode="0150"),
            "lines": [Line(sku="A-1", quantity=1, ship_to=Address(city="Oslo"))],
            "note": None,
            "level": 3,
            "extras": [],
        }
        assert values["priority"] is Priority.HIGH

    def test_nested_values_are_model_instances_two_levels_down(self) -> None:
        values = PydanticValidator(Everything).validate(_arguments(), CONTEXT)
        (line,) = values["lines"]
        assert isinstance(line, Line)
        assert isinstance(line.ship_to, Address)

    def test_values_are_keyed_by_field_name_whatever_the_wire_called_them(self) -> None:
        values = PydanticValidator(_Wire).validate({"firstName": "Ada", "memo": "hi"}, CONTEXT)
        assert values == {"first_name": "Ada", "note": "hi"}

    def test_the_context_reaches_pydantic_s_validators(self) -> None:
        context = ValidationContext(principal="ada", target=SimpleNamespace(title="Old"))
        validator = PydanticValidator(_Titled)
        assert validator.validate({"title": "New"}, context) == {"title": "New"}
        with pytest.raises(InvalidArguments) as caught:
            validator.validate({"title": "Old"}, context)
        assert caught.value.detail == {"title": ["Value error, ada gave it that title already."]}

    def test_an_offset_less_date_time_stays_naive_as_pydantic_leaves_it(self) -> None:
        values = PydanticValidator(Everything).validate(
            _arguments(at="2024-06-01T12:00:00"), CONTEXT
        )
        assert values["at"] == dt.datetime(2024, 6, 1, 12)
        assert values["at"].tzinfo is None


class TestRefusals:
    def test_every_failure_is_reported_in_pydantic_s_words(self) -> None:
        detail = _refusal(Everything, {**_arguments(count="two"), "name": None})
        assert detail == {
            "name": ["Input should be a valid string"],
            "count": ["Input should be a valid integer, unable to parse string as an integer"],
        }

    def test_rows_are_addressed_by_int_index_and_only_the_rows_that_failed(self) -> None:
        detail = _refusal(Everything, _arguments(lines=[_line(), _line(quantity="many")]))
        assert detail == {
            "lines": {
                1: {
                    "quantity": [
                        "Input should be a valid integer, unable to parse string as an integer"
                    ]
                }
            }
        }
        (index,) = detail["lines"]
        assert type(index) is int

    def test_a_model_validator_refusal_at_the_top_is_about_the_model(self) -> None:
        assert _refusal(Range, {"start": 2, "end": 1}) == {NON_FIELD_ERRORS: [RANGE_REFUSED]}

    def test_a_nested_model_refusing_itself_is_addressed_inside_it(self) -> None:
        detail = _refusal(Schedule, {"ranges": [], "first": {"start": 2, "end": 1}})
        assert detail == {"first": {NON_FIELD_ERRORS: [RANGE_REFUSED]}}

    def test_a_row_refusing_itself_or_not_an_object_is_addressed_inside_the_row(self) -> None:
        detail = _refusal(
            Schedule, {"ranges": [{"start": 1, "end": 2}, {"start": 2, "end": 1}, "3-4"]}
        )
        assert detail == {
            "ranges": {
                1: {NON_FIELD_ERRORS: [RANGE_REFUSED]},
                2: {NON_FIELD_ERRORS: ["Input should be a valid dictionary or instance of Range"]},
            }
        }

    def test_a_dict_value_is_addressed_by_its_key(self) -> None:
        detail = _refusal(_Scores, {"scores": {"a": 1, "b": "x"}})
        assert detail == {
            "scores": {
                "b": ["Input should be a valid integer, unable to parse string as an integer"]
            }
        }

    @pytest.mark.parametrize("model", [_Wire, _Located])
    def test_the_tree_says_the_parameter_name_however_pydantic_located_it(
        self, model: type[BaseModel]
    ) -> None:
        detail = _refusal(model, {"firstName": 1.5})
        assert list(detail) == ["firstName"]

    def test_an_undeclared_key_a_model_forbids_is_addressed_at_the_key(self) -> None:
        detail = _refusal(_Closed, {"name": "a", "colour": "red"})
        assert detail == {"colour": ["Extra inputs are not permitted"]}

    def test_a_message_about_a_node_with_messages_inside_it_goes_beside_them(self) -> None:
        # Only reachable by a caller skipping the shape check: a dict key that is
        # not a string, refused both as a key and, separately, for its value.
        detail = _refusal(_Labels, {"labels": {1: 2}})
        assert detail == {
            "labels": {
                1: {
                    "[key]": ["Input should be a valid string"],
                    NON_FIELD_ERRORS: ["Input should be a valid string"],
                }
            }
        }


class TestAgainstTheShapeCheck:
    """The kernel's shape check runs before the validator, so each test is sized
    to show which of the two answers."""

    def test_a_wrong_json_type_is_refused_by_the_shape_check_in_the_kernel_s_words(self) -> None:
        parameters = PydanticValidator(Everything).parameters()
        with pytest.raises(InvalidArguments) as caught:
            check_arguments(parameters, _arguments(count="two"))
        assert caught.value.detail == {"count": ["Expected an integer."]}
        assert "Input should be" not in str(caught.value.detail)

    def test_pydantic_answers_for_what_the_declaration_does_not_carry(self) -> None:
        validator = PydanticValidator(_Bounded)
        # Parameters carry no bounds, so the shape check passes the argument...
        assert check_arguments(validator.parameters(), {"name": "Adam"}) == {"name": "Adam"}
        # ...and the model refuses it.
        with pytest.raises(InvalidArguments) as caught:
            validator.validate({"name": "Adam"}, CONTEXT)
        assert caught.value.detail == {"name": ["String should have at most 3 characters"]}

    def test_a_row_past_the_bound_passes_the_shape_check_and_is_still_validated(self) -> None:
        validator = PydanticValidator(Node)
        arguments = _tree(7, {"name": 7})
        assert check_arguments(validator.parameters(), arguments) == arguments
        with pytest.raises(InvalidArguments) as caught:
            validator.validate(arguments, CONTEXT)
        detail: Any = caught.value.detail
        for _ in range(6):
            detail = detail["children"][0]
        assert detail == {"name": ["Input should be a valid string"]}

    def test_a_model_refusing_itself_past_the_bound_is_addressed_inside_it(self) -> None:
        # Past the bound the declaration says "object" and no more, so the
        # address is found by reading the model again, not from the description.
        arguments: dict[str, Any] = {"start": 2, "end": 1}
        for _ in range(6):
            arguments = {"start": 0, "end": 9, "inner": arguments}
        detail: Any = _refusal(_Span, arguments)
        for _ in range(6):
            (detail,) = detail.values()
        assert detail == {NON_FIELD_ERRORS: ["Value error, The span ends before it starts."]}

    def test_a_valid_tree_deeper_than_the_bound_is_built_in_full(self) -> None:
        values = PydanticValidator(Node).validate(_tree(7, {"name": "leaf"}), CONTEXT)
        node = Node(name="root", children=values["children"])
        depth = 0
        while node.children:
            (node,) = node.children
            depth += 1
        assert (depth, node.name) == (6, "leaf")


@pytest.mark.django_db
class TestRelationWrite:
    def test_a_validated_row_reaches_a_relation_write(self) -> None:
        data = PydanticValidator(_AuthorIn).validate(
            {"name": "Ursula", "books": [{"title": "Lathe", "price": "12.5"}]}, CONTEXT
        )
        change = create_from_input(
            Author, data, relations={"books": ChildSpec(model=Book, fk="author")}
        )
        (book,) = Book.objects.all()
        assert (book.author, book.title, book.price, book.status) == (
            change.instance,
            "Lathe",
            Decimal("12.50"),
            Status.DRAFT,
        )
        (books,) = change.children
        assert (books.relation, books.created) == ("books", (book.pk,))


class _Tagged(BaseModel):
    modes: list[Literal["fast", "slow"]]
    colours: list[Colour]
    statuses: list[Status]


def test_a_list_of_choices_declares_them_for_each_element() -> None:
    # ``items`` holds only the element's JSON type, and an array's choices
    # constrain each element, so a list of choices keeps them there: where the
    # shape check and the JSON Schema read them.
    params = PydanticValidator(_Tagged).parameters()
    assert [(p.name, p.items, p.choices) for p in params] == [
        ("modes", "string", ("fast", "slow")),
        ("colours", "string", ("red", "blue")),
        ("statuses", "string", ("draft", "published")),
    ]


class _Gaps(BaseModel):
    scores: list[int | None]
    addresses: list[Address | None]
    modes: list[Literal["fast", None]]
    tags: list[str]


class _Sparse(BaseModel):
    """A tree whose child lists may hold a gap, down past the appearance bound."""

    name: str
    children: list[_Sparse | None] = []


def test_a_nullable_element_is_declared_on_the_array_and_not_as_the_array() -> None:
    params = PydanticValidator(_Gaps).parameters()
    assert [(p.name, p.items_nullable, p.nullable) for p in params] == [
        ("scores", True, False),
        ("addresses", True, False),
        ("modes", True, False),
        ("tags", False, False),
    ]
    modes = params.get("modes")
    assert modes is not None and modes.choices == ("fast",)


def test_a_truncated_row_keeps_its_nullability() -> None:
    # Past the bound a row is declared as an object with no fields, and a gap
    # in the list is still pydantic's to accept, so it stays declared.
    children = PydanticValidator(_Sparse).parameters().get("children")
    for _ in range(3):
        assert children is not None and isinstance(children.items, Parameters)
        assert children.items_nullable
        children = children.items.get("children")
    assert children is not None
    assert (children.items, children.items_nullable) == ("object", True)


def test_the_shape_check_passes_the_null_elements_the_validator_takes() -> None:
    # Dispatch runs the shape check before the Validator, so a null element the
    # declaration did not call nullable was refused before this adapter saw it.
    params = PydanticValidator(_Gaps).parameters()
    arguments = {
        "scores": [1, None],
        "addresses": [None, {"city": "Oslo"}],
        "modes": [None, "fast"],
        "tags": ["a"],
    }
    values = PydanticValidator(_Gaps).validate(check_arguments(params, arguments), CONTEXT)
    assert values == {
        "scores": [1, None],
        "addresses": [None, Address(city="Oslo")],
        "modes": [None, "fast"],
        "tags": ["a"],
    }
    with pytest.raises(InvalidArguments) as caught:
        check_arguments(params, {**arguments, "tags": [None]})
    assert caught.value.detail == {"tags": {0: ["Expected a string."]}}


class _Ratio(BaseModel):
    ratio: float


@dataclass
class _RatioRow:
    ratio: float


class _RatioForm(forms.Form):
    ratio = forms.FloatField()


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_which_validators_take_the_non_finite_float_the_shape_check_refuses(
    value: float,
) -> None:
    # The arguments page names them: JSON has no spelling for the value, so the
    # shape check refuses it as outside the number type, where two of the
    # validators behind it would have taken it from a Python caller and
    # Django's number field refuses it in the same words.
    for validator in (PydanticValidator(_Ratio), DataclassValidator(_RatioRow)):
        assert not math.isfinite(validator.validate({"ratio": value}, CONTEXT)["ratio"])
        with pytest.raises(InvalidArguments) as caught:
            check_arguments(validator.parameters(), {"ratio": value})
        assert caught.value.detail == {"ratio": ["Enter a number."]}
    with pytest.raises(InvalidArguments) as caught:
        FormValidator(_RatioForm).validate({"ratio": value}, CONTEXT)
    assert caught.value.detail == {"ratio": ["Enter a number."]}


class _Labelled(BaseModel):
    status: Status
    priorities: list[Priority]
    colour: Colour
    mode: Literal["fast", "slow"]


class TestChoiceLabels:
    def test_a_django_choices_enum_labels_its_values_and_nothing_else_does(self) -> None:
        labels = {p.name: p.choice_labels for p in PydanticValidator(_Labelled).parameters()}
        assert labels == {
            "status": (("draft", "Draft"), ("published", "Published")),
            # A list's labels are its element's, beside its choices.
            "priorities": ((1, "Low"), (2, "High")),
            # A plain Enum and a Literal have no label of their own.
            "colour": None,
            "mode": None,
        }


class TestPartial:
    @pytest.mark.parametrize("method", ["validate", "validated"])
    def test_a_partial_call_is_refused_as_the_spec_s_error(self, method: str) -> None:
        # A model validates whole: a field it requires and was not sent is
        # missing, and its model validators assume every field is there.
        with pytest.raises(
            ImproperlyConfigured,
            match=re.escape(
                "PydanticValidator(Address) cannot validate a partial call: a pydantic "
                "model validates every field."
            ),
        ):
            getattr(PydanticValidator(Address), method)(
                {"city": "Oslo"}, ValidationContext(None, partial=True)
            )

    def test_a_partial_spec_over_it_is_refused_when_declared(self) -> None:
        # Not on the first call: a spec reaches transports that dispatch it
        # without ever asking, and every call would raise.
        with pytest.raises(ImproperlyConfigured) as refused:
            ServiceSpec(service=print, validator=PydanticValidator(Address), partial=True)
        message = str(refused.value)
        assert "declares partial=True with a PydanticValidator" in message
        assert "which cannot validate a partial call" in message

    def test_a_whole_call_is_the_mapping_as_its_data(self) -> None:
        validated = PydanticValidator(Address).validated({"city": "Oslo"}, CONTEXT)
        assert validated.values == {"city": "Oslo", "postcode": None}
        assert validated.data is validated.values


class _Colour(enum.Enum):
    RED = "red"


class _Coded(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(max_length=3)
    short: str = Field(default="ok", min_length=2)
    count: int = Field(default=1, ge=1, le=9, multiple_of=1)
    ratio: float = Field(default=0.5, gt=0, lt=1)
    few: list[int] = Field(default=[1], min_length=1, max_length=2)
    colour: _Colour = _Colour.RED
    price: Decimal = Field(default=Decimal(1), max_digits=4, decimal_places=2)
    even: int = Field(default=2, multiple_of=2)
    kind: Literal["draft", "final"] = "draft"
    tags: list[str] = []
    slug: str = "ok"
    note: str | None = "fine"

    @field_validator("note")
    @classmethod
    def _note(cls, value: str | None) -> str | None:
        # A refusal of ``None`` that is no type's: its code is the validator's.
        if value is None:
            raise ValueError("Say something.")
        return value

    @field_validator("slug")
    @classmethod
    def _slug(cls, value: str) -> str:
        if value == "raise":
            raise ValueError("No.")
        if value == "custom":
            raise PydanticCustomError("not_a_slug", "Not a slug.")
        return value


class TestRefusalCodes:
    """pydantic's error types mapped to the code a DRF field gives the same mistake."""

    @pytest.mark.parametrize(
        ("arguments", "field", "code"),
        [
            pytest.param({}, "title", "required", id="missing"),
            pytest.param({"title": None}, "title", "null", id="none"),
            pytest.param({"title": "long"}, "title", "max_length", id="string-too-long"),
            pytest.param(
                {"title": "t", "short": "s"}, "short", "min_length", id="string-too-short"
            ),
            pytest.param({"title": "t", "few": []}, "few", "min_length", id="list-too-short"),
            pytest.param({"title": "t", "few": [1, 2, 3]}, "few", "max_length", id="list-too-long"),
            pytest.param({"title": "t", "count": 0}, "count", "min_value", id="below"),
            pytest.param({"title": "t", "count": 10}, "count", "max_value", id="above"),
            pytest.param({"title": "t", "ratio": 0}, "ratio", "min_value", id="exclusive-below"),
            pytest.param({"title": "t", "ratio": 1}, "ratio", "max_value", id="exclusive-above"),
            pytest.param({"title": "t", "kind": "gone"}, "kind", "invalid_choice", id="literal"),
            pytest.param({"title": "t", "colour": "blue"}, "colour", "invalid_choice", id="enum"),
            pytest.param({"title": "t", "price": "12345"}, "price", "max_digits", id="digits"),
            pytest.param(
                {"title": "t", "price": "1.234"}, "price", "max_decimal_places", id="places"
            ),
            pytest.param(
                {"title": "t", "price": "123.4"}, "price", "max_whole_digits", id="whole-digits"
            ),
            pytest.param({"title": "t", "tags": "a"}, "tags", "not_a_list", id="list-type"),
            pytest.param({"title": "t", "nope": 1}, "nope", "unknown", id="extra"),
            pytest.param({"title": 3}, "title", "invalid", id="type"),
            pytest.param({"title": "t", "count": "x"}, "count", "invalid", id="parsing"),
            pytest.param({"title": "t", "slug": "raise"}, "slug", "invalid", id="value-error"),
            pytest.param({"title": "t", "note": None}, "note", "invalid", id="value-error-on-none"),
            pytest.param({"title": "t", "even": 3}, "even", "invalid", id="no-drf-code"),
            pytest.param({"title": "t", "slug": "custom"}, "slug", "not_a_slug", id="custom"),
        ],
    )
    def test_each_error_type_carries_its_code(
        self, arguments: dict[str, Any], field: str, code: str
    ) -> None:
        # On ``validate()`` itself: through dispatch, the shape check answers
        # an absent, a null and a wrongly typed argument first.
        refused = coded(_refusal(_Coded, arguments))
        assert [found for _, found in refused[field]] == [code]

    def test_a_missing_row_field_carries_required_at_its_address(self) -> None:
        refused = coded(_refusal(_AuthorIn, {"name": "Ada", "books": [{}]}))
        assert {code for _, code in refused["books"][0]["title"]} == {"required"}


class _Dated(BaseModel):
    prices: list[Decimal]
    at: list[dt.datetime]
    on: list[dt.date]


class TestDecimalElements:
    def test_a_list_of_decimals_declares_each_element_a_decimal(self) -> None:
        # A date or a date-time element takes no format on an array, so those
        # lists stay arrays of strings: without the decimal condition in
        # ``element_format`` this model could not be declared at all.
        params = PydanticValidator(_Dated).parameters()
        assert [(p.name, p.items, p.format) for p in params] == [
            ("prices", "string", "decimal"),
            ("at", "string", None),
            ("on", "string", None),
        ]

    def test_the_shape_check_takes_each_decimal_element_as_the_model_does(self) -> None:
        validator = PydanticValidator(_Dated)
        arguments = {"prices": [1.5, "2.25", 3], "at": [], "on": []}
        assert check_arguments(validator.parameters(), arguments) == arguments
        assert validator.validate(arguments, CONTEXT)["prices"] == [
            Decimal("1.5"),
            Decimal("2.25"),
            Decimal("3"),
        ]

    def test_an_element_that_is_no_decimal_is_refused_at_its_index(self) -> None:
        with pytest.raises(InvalidArguments) as caught:
            check_arguments(
                PydanticValidator(_Dated).parameters(),
                {"prices": ["1", "many"], "at": [], "on": []},
            )
        assert coded(caught.value.detail) == {"prices": {1: [("Enter a number.", "invalid")]}}

    def test_a_query_string_splits_a_list_of_decimals_on_its_commas(self) -> None:
        request = RequestFactory().get("/", {"prices": "1.5,2.25"})
        parameters = PydanticValidator(_Dated).parameters()
        assert request_arguments(request, parameters) == {"prices": ["1.5", "2.25"]}


class _Row(BaseModel):
    tags: list[str] = Field(default=[], max_length=2)


class _Lengths(BaseModel):
    keyword: list[int] = Field(default=[], max_length=1500)
    annotated: Annotated[list[int], Field(min_length=2, max_length=9)] = [1, 2]
    constrained: conlist(int, min_length=1, max_length=7) = [1]
    grouped: Annotated[list[int], Len(1, 3)] = [1]
    inner_field: Annotated[list[int], Field(max_length=4)] | None = None
    inner_raw: Annotated[list[int], MaxLen(3), MinLen(1)] | None = None
    # pydantic applies a field's metadata in order, the annotation's first,
    # and a later length replaces an earlier one, so each of these takes the
    # last it declares: 8 over 6, 3 over 1, then 6 over the 8 of the
    # annotation.
    later: Annotated[list[int], MaxLen(6), MaxLen(8)] = []
    fewest: Annotated[list[int], MinLen(1), MinLen(3)] = [1, 2, 3]
    outer: Annotated[list[int], MaxLen(8)] | None = Field(default=None, max_length=6)
    # Two layers inside the annotation, which pydantic leaves there: the
    # inner 6 first, then the outer 8 over it.
    deep: Annotated[Annotated[list[int], MaxLen(6)] | None, MaxLen(8)] | None = None
    # Metadata that is no length is passed over.
    noted: Annotated[list[int], "unrelated", MaxLen(2)] = []
    open: list[int] = []
    rows: list[_Row] = []
    # A length on anything but an array is the model's alone.
    name: str = Field(default="", max_length=3)
    scores: dict[str, int] = Field(default={}, max_length=2)


def _lengths(parameters: Parameters) -> list[tuple[str, int | None, int | None]]:
    return [(p.name, p.min_length, p.max_length) for p in parameters]


class TestDeclaredLengths:
    def test_every_spelling_of_a_list_s_length_is_declared(self) -> None:
        params = PydanticValidator(_Lengths).parameters()
        assert _lengths(params) == [
            ("keyword", None, 1500),
            ("annotated", 2, 9),
            ("constrained", 1, 7),
            ("grouped", 1, 3),
            ("inner_field", None, 4),
            ("inner_raw", 1, 3),
            ("later", None, 8),
            ("fewest", 3, None),
            ("outer", None, 6),
            ("deep", None, 8),
            ("noted", None, 2),
            ("open", None, None),
            ("rows", None, None),
            ("name", None, None),
            ("scores", None, None),
        ]
        rows = params.get("rows")
        assert rows is not None
        (tags,) = rows.nested or ()
        assert (tags.name, tags.max_length) == ("tags", 2)

    def test_each_declared_length_is_the_one_pydantic_enforces(self) -> None:
        # Sized one past each declared maximum and one short of each minimum,
        # so the model refuses exactly the arguments the declaration says it
        # will: the order rule above is pydantic's, not a guess.
        validator = PydanticValidator(_Lengths)
        for param in validator.parameters():
            if param.max_length is not None and param.nested is None:
                refused = coded(_refusal(_Lengths, {param.name: [1] * (param.max_length + 1)}))
                assert [code for _, code in refused[param.name]] == ["max_length"], param.name
                validator.validate({param.name: [1] * param.max_length}, CONTEXT)
            if param.min_length is not None:
                refused = coded(_refusal(_Lengths, {param.name: [1] * (param.min_length - 1)}))
                assert [code for _, code in refused[param.name]] == ["min_length"], param.name
                validator.validate({param.name: [1] * param.min_length}, CONTEXT)

    def test_a_list_the_model_allows_past_the_default_passes_the_shape_check(self) -> None:
        # 1500 is past the 1000 every undeclared array is held to, so only the
        # model's own maximum lets this through.
        parameters = PydanticValidator(_Lengths).parameters()
        arguments = {"keyword": list(range(1500))}
        assert check_arguments(parameters, arguments) == arguments
        schema = parameters_schema(parameters)["properties"]
        assert (schema["keyword"]["maxItems"], schema["annotated"]["minItems"]) == (1500, 2)

    def test_a_list_past_its_length_is_refused_by_the_shape_check_with_the_model_s_code(
        self,
    ) -> None:
        # Through dispatch the shape check answers first, in the kernel's words;
        # ``validate()`` alone answers in pydantic's. The code is the same.
        parameters = PydanticValidator(_Lengths).parameters()
        with pytest.raises(InvalidArguments) as caught:
            check_arguments(parameters, {"keyword": [1] * 1501, "annotated": [1]})
        assert coded(caught.value.detail) == {
            "keyword": [("Ensure this field has no more than 1500 elements.", "max_length")],
            "annotated": [("Ensure this field has at least 2 elements.", "min_length")],
        }
        refused = coded(_refusal(_Lengths, {"keyword": [1] * 1501}))
        assert refused["keyword"] == [
            ("List should have at most 1500 items after validation, not 1501", "max_length")
        ]
