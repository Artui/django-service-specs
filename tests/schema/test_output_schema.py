from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.utils import translation
from django.utils.translation import gettext_lazy

from django_service_specs.output.field_audience import FieldAudience
from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.output.output import Output
from django_service_specs.output.output_field import OutputField
from django_service_specs.schema.output_schema import output_schema

PUBLISHER = Output((OutputField("name", "string"),))
BOOK = Output(
    (
        OutputField("id", "integer"),
        OutputField("title", "string"),
        OutputField("publisher", "object", fields=PUBLISHER),
    )
)


def one(field: OutputField) -> dict[str, Any]:
    """The schema of a single field, as it sits among its item's properties."""
    return output_schema(Output((field,)))["properties"][field.name]


def walk(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Every schema node - the root, each property, each array's items - however deep."""
    nodes = [schema]
    for prop in schema.get("properties", {}).values():
        nodes += walk(prop)
    if "items" in schema:
        nodes += walk(schema["items"])
    return nodes


class TestItems:
    def test_an_item_lists_its_fields_and_requires_every_always_present_one(self) -> None:
        assert output_schema(BOOK) == {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "title": {"type": "string"},
                "publisher": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
            "required": ["id", "title", "publisher"],
        }

    def test_a_key_that_may_be_missing_is_not_required(self) -> None:
        schema = output_schema(
            Output(
                (
                    OutputField("bio", "string", always_present=False),
                    OutputField("name", "string"),
                )
            )
        )

        assert list(schema["properties"]) == ["bio", "name"]
        assert schema["required"] == ["name"]

    def test_with_no_always_present_field_required_is_left_out(self) -> None:
        assert output_schema(Output((OutputField("bio", "string", always_present=False),))) == {
            "type": "object",
            "properties": {"bio": {"type": "string"}},
        }

    def test_an_empty_output_is_an_object_with_no_properties(self) -> None:
        assert output_schema(Output()) == {"type": "object", "properties": {}}

    def test_output_is_never_closed_at_any_depth(self) -> None:
        nested = Output((OutputField("books", "array", items=BOOK),))

        assert [
            node for node in walk(output_schema(nested)) if "additionalProperties" in node
        ] == []


class TestFields:
    @pytest.mark.parametrize("json_type", ["string", "integer", "number", "boolean"])
    def test_a_scalar_states_its_type(self, json_type: str) -> None:
        assert one(OutputField("value", json_type)) == {"type": json_type}

    @pytest.mark.parametrize("fmt", ["decimal", "date-time", "date"])
    def test_a_format_is_stated_beside_its_type(self, fmt: str) -> None:
        assert one(OutputField("value", "string", format=fmt)) == {"type": "string", "format": fmt}

    def test_a_nullable_field_admits_null_by_its_type(self) -> None:
        assert one(OutputField("on", "string", format="date", nullable=True)) == {
            "type": ["string", "null"],
            "format": "date",
        }

    def test_a_nullable_object_admits_null_beside_its_properties(self) -> None:
        assert one(OutputField("publisher", "object", fields=PUBLISHER, nullable=True)) == {
            "type": ["object", "null"],
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }

    def test_an_object_with_no_fields_is_a_free_form_object(self) -> None:
        assert one(OutputField("meta", "object")) == {"type": "object"}

    def test_an_array_of_a_type_name_states_the_type_of_its_items(self) -> None:
        assert one(OutputField("ids", "array", items="integer", nullable=True)) == {
            "type": ["array", "null"],
            "items": {"type": "integer"},
        }

    def test_an_array_of_nested_items_describes_each_as_an_object(self) -> None:
        assert one(OutputField("publishers", "array", items=PUBLISHER)) == {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        }

    def test_an_array_with_no_items_says_nothing_of_its_elements(self) -> None:
        assert one(OutputField("anything", "array")) == {"type": "array", "items": {}}


class TestTitles:
    def test_a_label_is_the_title(self) -> None:
        assert one(OutputField("vat_id", "string", label="VAT number")) == {
            "type": "string",
            "title": "VAT number",
        }

    def test_a_field_with_no_label_has_no_title(self) -> None:
        assert one(OutputField("vat_id", "string")) == {"type": "string"}

    def test_a_lazy_label_is_rendered_in_the_active_language(self) -> None:
        with translation.override("fr"):
            title = one(OutputField("email", "string", label=gettext_lazy("Email address")))[
                "title"
            ]

        assert type(title) is str
        assert title == "Adresse électronique"


class TestChoices:
    def test_choices_whose_display_is_the_value_are_an_enum(self) -> None:
        assert one(OutputField("size", "integer", choices=[(1, "1"), (2, "2")])) == {
            "type": "integer",
            "enum": [1, 2],
        }

    def test_choices_with_a_display_of_their_own_are_a_one_of_with_titles(self) -> None:
        # One differing display is enough: every value then carries its own.
        status = OutputField("status", "string", choices=[("draft", "Draft"), ("x", "x")])

        assert one(status) == {
            "type": "string",
            "oneOf": [{"const": "draft", "title": "Draft"}, {"const": "x", "title": "x"}],
        }

    def test_a_nullable_enum_adds_null(self) -> None:
        assert one(OutputField("size", "integer", choices=[(1, "1")], nullable=True)) == {
            "type": ["integer", "null"],
            "enum": [1, None],
        }

    def test_a_nullable_one_of_adds_a_null_const_with_no_title(self) -> None:
        status = OutputField("status", "string", choices=[("draft", "Draft")], nullable=True)

        assert one(status) == {
            "type": ["string", "null"],
            "oneOf": [{"const": "draft", "title": "Draft"}, {"const": None}],
        }

    def test_a_nullable_field_whose_choices_list_null_lists_it_once(self) -> None:
        # A second null const would make oneOf match null twice, which refuses it.
        status = OutputField(
            "status", "string", choices=[("a", "A"), (None, "Unset")], nullable=True
        )
        size = OutputField("size", "integer", choices=[(1, "1"), (None, "None")], nullable=True)

        assert one(status)["oneOf"] == [
            {"const": "a", "title": "A"},
            {"const": None, "title": "Unset"},
        ]
        assert one(size)["enum"] == [1, None]

    def test_a_lazy_display_is_rendered_in_the_active_language(self) -> None:
        answer = OutputField("answer", "string", choices=[("y", gettext_lazy("Yes"))])

        with translation.override("fr"):
            [choice] = one(answer)["oneOf"]

        assert type(choice["title"]) is str
        assert choice == {"const": "y", "title": "Oui"}

    def test_an_arrays_choices_describe_each_item_and_not_the_array(self) -> None:
        tags = OutputField("tags", "array", items="string", choices=[("r", "Red")], nullable=True)

        assert one(tags) == {
            "type": ["array", "null"],
            "items": {"type": "string", "oneOf": [{"const": "r", "title": "Red"}]},
        }

    def test_a_nullable_element_admits_null_in_its_items_and_its_choices(self) -> None:
        tags = OutputField(
            "tags", "array", items="string", choices=[("r", "Red")], items_nullable=True
        )
        sizes = OutputField(
            "sizes", "array", items="integer", choices=[(1, "1")], items_nullable=True
        )

        # The array itself stays non-null: the two are independent.
        assert one(tags) == {
            "type": "array",
            "items": {
                "type": ["string", "null"],
                "oneOf": [{"const": "r", "title": "Red"}, {"const": None}],
            },
        }
        assert one(sizes)["items"] == {"type": ["integer", "null"], "enum": [1, None]}

    def test_a_nullable_nested_item_admits_null_beside_its_properties(self) -> None:
        publishers = OutputField("publishers", "array", items=PUBLISHER, items_nullable=True)

        assert one(publishers) == {
            "type": "array",
            "items": {
                "type": ["object", "null"],
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        }

    def test_choices_json_cannot_carry_are_left_out_whole(self) -> None:
        rate = OutputField(
            "rate", "string", format="decimal", choices=[("1", "1"), (Decimal("2"), "2")]
        )

        assert one(rate) == {"type": "string", "format": "decimal"}


class TestNothingElse:
    def test_marking_is_not_emitted_and_a_hidden_field_is_described(self) -> None:
        fields = Output(
            (
                OutputField("id", "integer", marking=FieldMarking.handle()),
                OutputField(
                    "secret", "string", marking=FieldMarking(audience=FieldAudience.HIDDEN)
                ),
            )
        )

        assert output_schema(fields) == {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "secret": {"type": "string"}},
            "required": ["id", "secret"],
        }

    def test_no_reference_schema_key_or_default_at_any_depth(self) -> None:
        nested = Output((OutputField("books", "array", items=BOOK, label="Books"),))
        keys = {key for node in walk(output_schema(nested)) for key in node}

        assert keys.isdisjoint({"$ref", "$defs", "$schema", "default", "description"})

    def test_every_call_builds_a_new_schema(self) -> None:
        first = output_schema(BOOK)
        first["properties"]["publisher"]["properties"]["name"]["x-mine"] = True

        assert "x-mine" not in output_schema(BOOK)["properties"]["publisher"]["properties"]["name"]
