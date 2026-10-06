from __future__ import annotations

import dataclasses
import datetime as dt
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Literal

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db.models import QuerySet
from django.db.models.manager import BaseManager
from django.utils import translation
from pydantic import BaseModel, Field, ValidationError, computed_field
from pydantic.fields import ComputedFieldInfo, FieldInfo

from django_service_specs.adapters.pydantic.pydantic_presenter import PydanticPresenter
from django_service_specs.adapters.pydantic.pydantic_validator import PydanticValidator
from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.output.output import Output
from django_service_specs.output.output_field import OutputField
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.validation.validation_context import ValidationContext
from tests.adapter_app.models import Author, Book, Status
from tests.adapters.pydantic.utils import (
    Address,
    Answer,
    Colour,
    Everything,
    Line,
    Marked,
    Node,
    Priced,
)


class _Poll(BaseModel):
    answer: Answer


class _Wire(BaseModel):
    first_name: str = Field(alias="firstName")
    note: str | None = Field(None, serialization_alias="memo")


class _Invoice(BaseModel):
    net: Decimal = Field(title="Net amount")
    reference: str
    secret: str = Field("x", exclude=True)

    @computed_field(alias="grossAmount", title="Gross amount")
    @property
    def gross(self) -> Decimal:
        return self.net * 2


class _WiderAddress(Address):
    country: str


class _AuthorName(BaseModel):
    name: str


class _BookOut(BaseModel):
    title: str
    price: Decimal
    status: Status
    published_on: dt.date | None
    author: _AuthorName


class _ShelfBook(BaseModel):
    title: str


class _AuthorOut(BaseModel):
    name: str
    books: list[_ShelfBook]


def _everything() -> Everything:
    return Everything(
        name="Order",
        count=2,
        ratio=0.5,
        active=True,
        price=Decimal("12.50"),
        at=dt.datetime(2024, 6, 1, 12, tzinfo=dt.timezone.utc),
        on=dt.date(2024, 6, 1),
        status=Status.DRAFT,
        priority=2,
        colour="red",
        mode="fast",
        tags=["a", "b"],
        address=Address(city="Oslo", postcode="0150"),
        lines=[Line(pk=7, sku="A-1", quantity=1, ship_to=Address(city="Oslo"))],
    )


PRESENTED = {
    "name": "Order",
    "count": 2,
    "ratio": 0.5,
    "active": True,
    "price": "12.50",
    "at": "2024-06-01T12:00:00Z",
    "on": "2024-06-01",
    "status": "draft",
    "priority": 2,
    "colour": "red",
    "mode": "fast",
    "tags": ["a", "b"],
    "address": {"city": "Oslo", "postcode": "0150"},
    "lines": [
        {"pk": 7, "sku": "A-1", "quantity": 1, "ship_to": {"city": "Oslo", "postcode": None}}
    ],
    "note": None,
    "level": 3,
    "extras": [],
}
"""``_everything()`` as ``present`` renders it: pydantic's JSON encoding, by alias."""


def _tree(depth: int) -> SimpleNamespace:
    """A ``Node``-shaped object ``depth`` levels deep, one child per level."""
    children = [] if depth == 1 else [_tree(depth - 1)]
    return SimpleNamespace(name=f"level {depth}", children=children)


class TestConstruction:
    @pytest.mark.parametrize("model", [dict, Address(city="Oslo")])
    def test_refuses_anything_but_a_model_class(self, model: Any) -> None:
        with pytest.raises(
            ImproperlyConfigured, match="PydanticPresenter takes a pydantic model class"
        ):
            PydanticPresenter(model)


class TestOutput:
    def test_every_field_is_declared_in_order(self) -> None:
        output = PydanticPresenter(Everything).output()
        assert output.names() == tuple(PRESENTED)
        assert output.get("price") == OutputField("price", "string", format="decimal")
        assert output.get("at") == OutputField("at", "string", format="date-time")
        assert output.get("note") == OutputField("note", "string", nullable=True)
        assert output.get("tags") == OutputField("tags", "array", items="string")

    def test_computed_fields_follow_the_fields_and_excluded_ones_are_not_output(self) -> None:
        assert PydanticPresenter(_Invoice).output().names() == ("net", "reference", "grossAmount")

    def test_a_field_is_named_for_the_key_the_model_dumps_it_under(self) -> None:
        assert PydanticPresenter(_Wire).output().names() == ("firstName", "memo")

    def test_a_label_is_the_title_the_author_set_and_none_otherwise(self) -> None:
        output = PydanticPresenter(_Invoice).output()
        assert [f.label for f in output] == ["Net amount", None, "Gross amount"]

    def test_a_computed_field_is_typed_by_its_return_annotation(self) -> None:
        gross = PydanticPresenter(_Invoice).output().get("grossAmount")
        assert gross == OutputField("grossAmount", "string", format="decimal", label="Gross amount")

    def test_every_field_is_always_present(self) -> None:
        assert {f.always_present for f in PydanticPresenter(Everything).output()} == {True}

    @pytest.mark.skipif(
        "exclude_if" not in FieldInfo.__slots__, reason="exclude_if arrived in a later pydantic"
    )
    def test_a_field_the_model_may_leave_out_is_not_always_present(self) -> None:
        class Sparse(BaseModel):
            name: str
            note: str | None = Field(None, exclude_if=lambda value: value is None)

        presenter = PydanticPresenter(Sparse)
        assert [f.always_present for f in presenter.output()] == [True, False]
        assert presenter.present({"name": "a"}) == {"name": "a"}

    @pytest.mark.skipif(
        "exclude_if" not in {f.name for f in dataclasses.fields(ComputedFieldInfo)},
        reason="a computed field's exclude_if arrived in a later pydantic",
    )
    def test_a_computed_field_the_model_may_leave_out_is_not_always_present(self) -> None:
        class Sparse(BaseModel):
            name: str

            @computed_field(exclude_if=lambda value: value is None)
            @property
            def shout(self) -> str | None:
                return self.name.upper() or None

        presenter = PydanticPresenter(Sparse)
        assert [f.always_present for f in presenter.output()] == [True, False]
        assert presenter.present({"name": ""}) == {"name": ""}

    def test_choices_are_value_and_display_pairs(self) -> None:
        output = PydanticPresenter(Everything).output()
        # A Django Choices enum brings its label.
        assert output.get("status").choices == (("draft", "Draft"), ("published", "Published"))
        assert output.get("priority").choices == ((1, "Low"), (2, "High"))
        # A plain Enum and a Literal have no display, so the value stands in.
        assert output.get("colour").choices == (("red", "red"), ("blue", "blue"))
        assert output.get("mode").choices == (("fast", "fast"), ("slow", "slow"))

    def test_a_choices_label_is_read_in_the_language_active_when_output_is_called(self) -> None:
        presenter = PydanticPresenter(_Poll)
        assert presenter.output().get("answer").choices == (("y", "Yes"), ("n", "No"))
        with translation.override("fr"):
            assert presenter.output().get("answer").choices == (("y", "Oui"), ("n", "Non"))

    def test_a_marking_is_read_from_the_annotation_either_side_of_none(self) -> None:
        output = PydanticPresenter(Marked).output()
        assert output.get("id").marking == FieldMarking.handle()
        assert output.get("title").marking == FieldMarking.label()
        assert output.get("title").nullable is True
        assert output.get("internal").marking == FieldMarking.hidden()
        assert output.get("internal").nullable is True

    def test_nested_objects_and_rows_are_declared_as_outputs(self) -> None:
        output = PydanticPresenter(Everything).output()
        address = Output(
            (OutputField("city", "string"), OutputField("postcode", "string", nullable=True))
        )
        assert output.get("address") == OutputField("address", "object", fields=address)
        lines = output.get("lines")
        assert isinstance(lines.items, Output)
        assert lines.items.get("ship_to") == OutputField("ship_to", "object", fields=address)

    def test_a_tree_is_declared_to_the_bound_then_as_rows_of_objects(self) -> None:
        children = PydanticPresenter(Node).output().get("children")
        for _ in range(3):
            assert isinstance(children.items, Output)
            children = children.items.get("children")
        assert (children.type, children.items) == ("array", "object")


class TestPresent:
    def test_an_instance_is_rendered_by_the_model_as_json_data(self) -> None:
        assert PydanticPresenter(Everything).present(_everything()) == PRESENTED

    def test_none_is_presented_as_none(self) -> None:
        assert PydanticPresenter(Everything).present(None) is None

    def test_keys_are_the_output_names(self) -> None:
        presented = PydanticPresenter(_Wire).present(SimpleNamespace(first_name="Ada", note="hi"))
        assert presented == {"firstName": "Ada", "memo": "hi"}

    def test_computed_fields_are_rendered_and_excluded_fields_are_not(self) -> None:
        presented = PydanticPresenter(_Invoice).present(
            SimpleNamespace(net=Decimal("5"), reference="r-1", secret="s")
        )
        assert presented == {"net": "5", "reference": "r-1", "grossAmount": "10"}

    def test_a_mapping_is_read_by_field_name(self) -> None:
        presented = PydanticPresenter(_Wire).present({"first_name": "Ada", "note": None})
        assert presented == {"firstName": "Ada", "memo": None}

    def test_a_field_the_value_does_not_carry_is_left_to_the_model_s_default(self) -> None:
        assert PydanticPresenter(Priced).present(SimpleNamespace(net=Decimal("10"))) == {
            "net": "10",
            "rate": "0.25",
            "gross": "12.50",
        }

    def test_an_instance_of_a_subclass_is_read_to_the_declared_fields(self) -> None:
        wider = _WiderAddress(city="Oslo", country="NO")
        assert PydanticPresenter(Address).present(wider) == {"city": "Oslo", "postcode": None}

    def test_a_value_the_model_refuses_is_a_defect_and_raises(self) -> None:
        with pytest.raises(ValidationError, match="net"):
            PydanticPresenter(Priced).present({"net": "ten"})

    def test_a_tree_deeper_than_the_bound_is_rendered_in_full(self) -> None:
        presented = PydanticPresenter(Node).present(_tree(7))
        depth = 0
        while presented["children"]:
            (presented,) = presented["children"]
            depth += 1
        assert (depth, presented) == (6, {"name": "level 1", "children": []})


@pytest.mark.django_db
class TestModelRows:
    def test_a_row_is_read_through_its_foreign_key(self) -> None:
        author = Author.objects.create(name="Ann")
        Book.objects.create(author=author, title="One", price=Decimal("9.99"))
        # The choice column holds a plain str; the model declares the enum.
        assert PydanticPresenter(_BookOut).present(Book.objects.get()) == {
            "title": "One",
            "price": "9.99",
            "status": "draft",
            "published_on": None,
            "author": {"name": "Ann"},
        }

    def test_a_reverse_relation_is_a_manager_read_through_all(self) -> None:
        author = Author.objects.create(name="Ann")
        Book.objects.create(author=author, title="One", price=Decimal("9.99"))
        Book.objects.create(author=author, title="Two", price=Decimal("12.00"))
        assert PydanticPresenter(_AuthorOut).present(Author.objects.get()) == {
            "name": "Ann",
            "books": [{"title": "One"}, {"title": "Two"}],
        }

    def test_a_manager_built_on_base_manager_is_read_through_all_too(self) -> None:
        """``BaseManager.from_queryset`` builds a manager that is not a ``Manager``;
        a model whose default manager is one has related managers built on it too."""
        author = Author.objects.create(name="Ann")
        Book.objects.create(author=author, title="One", price=Decimal("9.99"))
        books: Any = BaseManager.from_queryset(QuerySet)()
        books.model = Book

        assert PydanticPresenter(_AuthorOut).present(SimpleNamespace(name="Ann", books=books)) == {
            "name": "Ann",
            "books": [{"title": "One"}],
        }


def _agree(parameters: Parameters, output: Output) -> None:
    """Each declared parameter has an output field of the same name and type."""
    for parameter in parameters:
        field = output.get(parameter.name)
        assert field is not None, parameter.name
        assert (field.type, field.format, field.nullable) == (
            parameter.type,
            parameter.format,
            parameter.nullable,
        ), parameter.name
        values = None if field.choices is None else tuple(value for value, _ in field.choices)
        assert parameter.choices == values, parameter.name
        if parameter.fields is not None:
            assert isinstance(field.fields, Output), parameter.name
            _agree(parameter.fields, field.fields)
        if isinstance(parameter.items, Parameters):
            assert isinstance(field.items, Output), parameter.name
            _agree(parameter.items, field.items)
        else:
            assert field.items == parameter.items, parameter.name


class TestAgainstTheValidator:
    def test_parameters_and_output_agree_field_for_field(self) -> None:
        parameters = PydanticValidator(Everything).parameters()
        output = PydanticPresenter(Everything).output()
        assert parameters.names() == set(output.names())
        _agree(parameters, output)

    def test_they_differ_where_the_model_computes_or_excludes_a_field(self) -> None:
        assert PydanticValidator(_Invoice).parameters().names() == {"net", "reference", "secret"}
        assert PydanticPresenter(_Invoice).output().names() == ("net", "reference", "grossAmount")

    def test_what_the_validator_builds_the_presenter_renders_as_it_came_in(self) -> None:
        arguments = {name: PRESENTED[name] for name in PRESENTED if name not in {"note", "level"}}
        values = PydanticValidator(Everything).validate(
            arguments, ValidationContext(principal=None)
        )
        assert PydanticPresenter(Everything).present(values) == PRESENTED


class _Tagged(BaseModel):
    modes: list[Literal["fast", "slow"]]
    colours: list[Colour]
    statuses: list[Status]


def test_a_list_of_choices_declares_their_pairs_for_each_element() -> None:
    # ``items`` holds only the element's JSON type, and an array's choices
    # constrain each element, so a list of choices keeps them there: where the
    # shape check and the JSON Schema read them.
    output = PydanticPresenter(_Tagged).output()
    assert output.get("modes").choices == (("fast", "fast"), ("slow", "slow"))
    assert output.get("colours").choices == (("red", "red"), ("blue", "blue"))
    assert output.get("statuses").choices == (("draft", "Draft"), ("published", "Published"))


class _Gaps(BaseModel):
    scores: list[int | None]
    addresses: list[Address | None]
    tags: list[str]


def test_a_nullable_element_is_declared_on_the_array_and_not_as_the_array() -> None:
    output = PydanticPresenter(_Gaps).output()
    assert [(f.name, f.items_nullable, f.nullable) for f in output] == [
        ("scores", True, False),
        ("addresses", True, False),
        ("tags", False, False),
    ]
    presented = PydanticPresenter(_Gaps).present(
        {"scores": [1, None], "addresses": [None, {"city": "Oslo"}], "tags": []}
    )
    assert presented == {
        "scores": [1, None],
        "addresses": [None, {"city": "Oslo", "postcode": None}],
        "tags": [],
    }
