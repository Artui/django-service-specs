from __future__ import annotations

import datetime as dt
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Literal

import pytest
from django.core.exceptions import ImproperlyConfigured
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    computed_field,
    field_validator,
    model_validator,
)

from django_service_specs.adapters.dataclass.dataclass_validator import DataclassValidator
from django_service_specs.adapters.pydantic.pydantic_validator import PydanticValidator
from django_service_specs.mutations.create_from_input import create_from_input
from django_service_specs.parameters.check_arguments import check_arguments
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.parameters.utils import NON_FIELD_ERRORS
from django_service_specs.relations.child_spec import ChildSpec
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
