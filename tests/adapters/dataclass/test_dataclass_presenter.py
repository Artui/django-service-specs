from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.utils import translation

from django_service_specs.adapters.dataclass.dataclass_presenter import DataclassPresenter
from django_service_specs.adapters.dataclass.dataclass_validator import DataclassValidator
from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.output.output import Output
from django_service_specs.output.output_field import OutputField
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.types.unset import UNSET
from django_service_specs.validation.validation_context import ValidationContext
from tests.adapter_app.models import Author, Book, Status
from tests.adapters.dataclass.utils import (
    Address,
    Answer,
    Colour,
    Computed,
    Everything,
    Line,
    Marked,
    Priority,
)


@dataclass
class _AuthorRef:
    name: str


@dataclass
class _BookOut:
    title: str
    price: Decimal
    status: Status
    published_on: dt.date | None
    author: _AuthorRef


@dataclass
class _BookBrief:
    title: str


@dataclass
class _AuthorOut:
    name: str
    books: list[_BookBrief]


@dataclass
class _Poll:
    answer: Answer


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
        priority=Priority.HIGH,
        colour=Colour.RED,
        mode="fast",
        tags=["a", "b"],
        address=Address("Oslo", "0150"),
        lines=[Line(pk=7, sku="A-1", quantity=1, ship_to=Address("Oslo"))],
    )


# --- construction ----------------------------------------------------------------


@pytest.mark.parametrize("cls", [dict, Address("Oslo")])
def test_refuses_anything_but_a_dataclass_type(cls: Any) -> None:
    with pytest.raises(ImproperlyConfigured, match="DataclassPresenter takes a dataclass type"):
        DataclassPresenter(cls)


# --- output() --------------------------------------------------------------------------


def test_output_declares_every_field_in_order() -> None:
    output = DataclassPresenter(Everything).output()
    assert output.names() == (
        "name",
        "count",
        "ratio",
        "active",
        "price",
        "at",
        "on",
        "status",
        "priority",
        "colour",
        "mode",
        "tags",
        "address",
        "lines",
        "note",
        "bio",
        "level",
        "extras",
    )
    assert output.get("price") == OutputField("price", "string", format="decimal")
    assert output.get("at") == OutputField("at", "string", format="date-time")
    assert output.get("note") == OutputField("note", "string", nullable=True)
    assert output.get("tags") == OutputField("tags", "array", items="string")


def test_labels_are_none_because_a_dataclass_has_none() -> None:
    assert {f.label for f in DataclassPresenter(Everything).output()} == {None}


def test_only_a_field_admitting_unset_type_may_be_absent() -> None:
    output = DataclassPresenter(Everything).output()
    assert [f.name for f in output if not f.always_present] == ["bio"]


def test_choices_are_value_and_display_pairs() -> None:
    output = DataclassPresenter(Everything).output()
    # A Django Choices enum brings its label.
    assert output.get("status").choices == (("draft", "Draft"), ("published", "Published"))
    assert output.get("priority").choices == ((1, "Low"), (2, "High"))
    # A plain Enum and a Literal have no display, so the value stands in.
    assert output.get("colour").choices == (("red", "red"), ("blue", "blue"))
    assert output.get("mode").choices == (("fast", "fast"), ("slow", "slow"))


def test_a_choices_label_is_read_in_the_language_active_when_output_is_called() -> None:
    presenter = DataclassPresenter(_Poll)
    assert presenter.output().get("answer").choices == (("y", "Yes"), ("n", "No"))
    with translation.override("fr"):
        assert presenter.output().get("answer").choices == (("y", "Oui"), ("n", "Non"))


def test_nested_objects_and_rows_are_declared_as_outputs() -> None:
    output = DataclassPresenter(Everything).output()
    address = Output(
        (OutputField("city", "string"), OutputField("postcode", "string", nullable=True))
    )
    assert output.get("address") == OutputField("address", "object", fields=address)
    lines = output.get("lines")
    assert isinstance(lines.items, Output)
    assert lines.items.get("ship_to") == OutputField("ship_to", "object", fields=address)


def test_a_marking_is_read_from_the_annotation_either_side_of_none() -> None:
    output = DataclassPresenter(Marked).output()
    assert output.get("id").marking == FieldMarking.handle()
    assert output.get("title").marking == FieldMarking.label()
    assert output.get("title").nullable is True
    assert output.get("internal").marking == FieldMarking.hidden()
    assert output.get("internal").nullable is True


def test_a_computed_field_is_output() -> None:
    assert DataclassPresenter(Computed).output().names() == ("base", "doubled")
    assert DataclassPresenter(Computed).present(Computed(2)) == {"base": 2, "doubled": 4}


# --- present() --------------------------------------------------------------------------


def test_present_encodes_to_json_like_data() -> None:
    assert DataclassPresenter(Everything).present(_everything()) == {
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
        "lines": [
            {"pk": 7, "sku": "A-1", "quantity": 1, "ship_to": {"city": "Oslo", "postcode": None}}
        ],
        "note": None,
        # bio is UNSET, so it is left out rather than rendered.
        "level": 3,
        "extras": [],
    }


def test_a_field_set_to_unset_is_left_out_and_one_set_to_none_is_not() -> None:
    presented = DataclassPresenter(Everything).present(_everything())
    assert "bio" not in presented
    assert presented["note"] is None
    rendered = DataclassPresenter(Everything).present(
        Everything(**{**vars(_everything()), "bio": "Hi"})
    )
    assert rendered["bio"] == "Hi"


def test_none_is_presented_as_none() -> None:
    assert DataclassPresenter(Everything).present(None) is None


def test_any_object_carrying_the_names_is_presented() -> None:
    row = SimpleNamespace(
        name="Ann", books=(SimpleNamespace(title="One", unrelated=1),), extra="unread"
    )
    assert DataclassPresenter(_AuthorOut).present(row) == {
        "name": "Ann",
        "books": [{"title": "One"}],
    }


@pytest.mark.django_db
def test_a_model_row_is_presented_through_its_relations() -> None:
    author = Author.objects.create(name="Ann")
    Book.objects.create(author=author, title="One", price=Decimal("9.99"))
    Book.objects.create(
        author=author,
        title="Two",
        price=Decimal("12.00"),
        status=Status.PUBLISHED,
        published_on=dt.date(2024, 6, 1),
    )
    first, second = Book.objects.order_by("pk")
    presenter = DataclassPresenter(_BookOut)
    # The choice column holds a plain str; the dataclass declares the enum.
    assert presenter.present(first) == {
        "title": "One",
        "price": "9.99",
        "status": "draft",
        "published_on": None,
        "author": {"name": "Ann"},
    }
    assert presenter.present(second)["published_on"] == "2024-06-01"
    # A reverse relation is a manager, read through .all().
    assert DataclassPresenter(_AuthorOut).present(Author.objects.get()) == {
        "name": "Ann",
        "books": [{"title": "One"}, {"title": "Two"}],
    }


# --- against the validator ----------------------------------------------------------------


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


def test_parameters_and_output_agree_field_for_field() -> None:
    parameters = DataclassValidator(Everything).parameters()
    output = DataclassPresenter(Everything).output()
    assert parameters.names() == set(output.names())
    _agree(parameters, output)


def test_they_differ_where_the_dataclass_computes_a_field() -> None:
    # A computed field comes out and never goes in.
    assert set(DataclassPresenter(Computed).output().names()) - DataclassValidator(
        Computed
    ).parameters().names() == {"doubled"}


def test_what_the_validator_builds_the_presenter_renders_as_it_came_in() -> None:
    arguments = {
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
        "lines": [
            {"pk": 7, "sku": "A-1", "quantity": 1, "ship_to": {"city": "Oslo", "postcode": None}}
        ],
    }
    values = DataclassValidator(Everything).validate(arguments, ValidationContext(principal=None))
    assert values["bio"] is UNSET
    presented = DataclassPresenter(Everything).present(Everything(**values))
    # What was sent comes back unchanged; what was omitted comes back as the
    # dataclass's defaults, and the UNSET field stays absent.
    assert presented == {**arguments, "note": None, "level": 3, "extras": []}
