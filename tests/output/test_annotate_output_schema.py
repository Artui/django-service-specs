from __future__ import annotations

from typing import Any

import pytest

from django_service_specs.output.annotate_output_schema import annotate_output_schema
from django_service_specs.output.audience_projection import AudienceProjection
from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.schema.output_schema import output_schema
from tests.output.test_project_payload import invoice_projection
from tests.output.utils import HANDLE_DESCRIPTION, INVOICE, PROJECTED_SCHEMA

LABELS = {"PENDING_REVIEW": "Awaiting review", 1: "Low"}
HIDDEN_ETAG = AudienceProjection(fields={"etag": FieldMarking.hidden()})


def annotate(schema: dict[str, Any], projection: AudienceProjection, **kwargs: Any) -> Any:
    return annotate_output_schema(schema, projection, **kwargs)


def test_mirrors_the_payload_projection_at_every_depth() -> None:
    schema = output_schema(INVOICE)

    annotated = annotate(schema, invoice_projection(), handle_description=HANDLE_DESCRIPTION)

    assert annotated == PROJECTED_SCHEMA


def test_leaves_the_schema_it_was_given_alone() -> None:
    schema = output_schema(INVOICE)

    annotate(schema, invoice_projection(), handle_description=HANDLE_DESCRIPTION)

    assert schema == output_schema(INVOICE)


def test_a_hidden_property_leaves_properties_and_required() -> None:
    schema = {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "etag": {"type": "string"}},
        "required": ["id", "etag"],
    }

    assert annotate(schema, HIDDEN_ETAG) == {
        "type": "object",
        "properties": {"id": {"type": "integer"}},
        "required": ["id"],
    }


def test_required_is_dropped_when_nothing_required_is_left() -> None:
    schema = {"type": "object", "properties": {"etag": {"type": "string"}}, "required": ["etag"]}

    assert annotate(schema, HIDDEN_ETAG) == {"type": "object", "properties": {}}


def test_a_list_schema_is_annotated_through_its_items() -> None:
    item = {"type": "object", "properties": {"id": {"type": "integer"}, "etag": {"type": "string"}}}

    assert annotate({"type": "array", "items": item}, HIDDEN_ETAG) == {
        "type": "array",
        "items": {"type": "object", "properties": {"id": {"type": "integer"}}},
    }


def test_a_schema_without_properties_is_returned_as_it_is() -> None:
    schema = {"type": "string"}

    assert annotate(schema, HIDDEN_ETAG) is schema


class TestPassingThrough:
    """Each condition of the early return, held by its own case."""

    def test_no_schema_is_still_no_schema(self) -> None:
        assert annotate_output_schema(None, HIDDEN_ETAG) is None

    def test_an_empty_projection_returns_the_schema_itself(self) -> None:
        schema = {"type": "object", "properties": {"etag": {"type": "string"}}}

        assert annotate(schema, AudienceProjection()) is schema


class TestDescriptions:
    SCHEMA: dict[str, Any] = {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "number": {"type": "string"}},
    }

    def test_an_unlabelled_handle_says_nothing_by_default(self) -> None:
        """What a reader should do with an identifier depends on the reader, so
        the wording is the transport's to supply."""
        projection = AudienceProjection(fields={"id": FieldMarking.handle()})

        assert annotate(self.SCHEMA, projection)["properties"]["id"] == {"type": "integer"}

    def test_an_unlabelled_handle_takes_the_wording_supplied(self) -> None:
        """The second condition of the marking's own wording: a marking that
        declares none falls back to the handle wording."""
        projection = AudienceProjection(fields={"id": FieldMarking.handle()})

        annotated = annotate(self.SCHEMA, projection, handle_description="Pass it on.")

        assert annotated["properties"]["id"] == {"type": "integer", "description": "Pass it on."}

    def test_the_markings_own_wording_wins(self) -> None:
        projection = AudienceProjection(fields={"id": FieldMarking.handle("The invoice handle.")})

        annotated = annotate(self.SCHEMA, projection, handle_description="Pass it on.")

        assert annotated["properties"]["id"]["description"] == "The invoice handle."

    def test_the_handle_wording_is_for_handles_only(self) -> None:
        """The first condition of the marking's own wording: an unmarked field
        has none, and is not a handle either."""
        projection = AudienceProjection(fields={"id": FieldMarking.handle()})

        annotated = annotate(self.SCHEMA, projection, handle_description="Pass it on.")

        assert annotated["properties"]["number"] == {"type": "string"}

    def test_a_label_carries_its_wording(self) -> None:
        projection = AudienceProjection(
            fields={"number": FieldMarking.label("The invoice number.")}, label="number"
        )

        annotated = annotate(self.SCHEMA, projection, handle_description="Pass it on.")

        assert annotated["properties"]["number"] == {
            "type": "string",
            "description": "The invoice number.",
        }


class TestChoices:
    def test_an_enum_is_restated_in_its_display_values(self) -> None:
        schema = {
            "type": "object",
            "properties": {"s": {"type": "string", "enum": ["PENDING_REVIEW", "X"]}},
        }
        projection = AudienceProjection(choice_labels={"s": LABELS})

        assert annotate(schema, projection)["properties"]["s"] == {
            "type": "string",
            "enum": ["Awaiting review", "X"],
        }

    def test_a_handle_keeps_its_constants(self) -> None:
        """The first condition of the substitution."""
        subschema = {"type": "string", "enum": ["PENDING_REVIEW"]}
        schema = {"type": "object", "properties": {"s": subschema}}
        projection = AudienceProjection(
            fields={"s": FieldMarking.handle()}, choice_labels={"s": LABELS}
        )

        assert annotate(schema, projection)["properties"]["s"] == subschema

    def test_a_field_with_no_labels_is_left_alone(self) -> None:
        """The second condition of the substitution."""
        subschema = {"type": "string", "enum": ["PENDING_REVIEW"]}
        schema = {"type": "object", "properties": {"s": subschema, "t": subschema}}
        projection = AudienceProjection(choice_labels={"s": LABELS})

        assert annotate(schema, projection)["properties"]["t"] == subschema

    def test_a_union_is_restated_member_by_member(self) -> None:
        """The shape an ``X | None`` reaches a schema in from elsewhere: each
        member is rewritten, and the null one passes through."""
        subschema = {"anyOf": [{"enum": ["PENDING_REVIEW"]}, {"type": "null"}]}
        schema = {"type": "object", "properties": {"s": subschema}}
        projection = AudienceProjection(choice_labels={"s": LABELS})

        assert annotate(schema, projection)["properties"]["s"] == {
            "anyOf": [{"enum": ["Awaiting review"]}, {"type": "null"}]
        }

    def test_a_one_of_member_with_no_constant_passes_through(self) -> None:
        subschema = {"oneOf": [{"const": "PENDING_REVIEW", "title": "x"}, {"type": "null"}]}
        schema = {"type": "object", "properties": {"s": subschema}}
        projection = AudienceProjection(choice_labels={"s": LABELS})

        assert annotate(schema, projection)["properties"]["s"] == {
            "oneOf": [{"const": "Awaiting review"}, {"type": "null"}]
        }

    def test_a_schema_with_no_choice_keyword_is_left_alone(self) -> None:
        subschema = {"type": "string"}
        schema = {"type": "object", "properties": {"s": subschema}}
        projection = AudienceProjection(choice_labels={"s": LABELS})

        assert annotate(schema, projection)["properties"]["s"] == subschema


class TestRestatedType:
    """A display is a string, so a stated type follows the values it now describes.

    Left as it was, an integer choice spoken as ``"Low"`` is described as an
    integer, and the projected payload fails the projected schema.
    """

    @staticmethod
    def spoken(subschema: dict[str, Any], labels: dict[Any, str] = LABELS) -> Any:
        schema = {"type": "object", "properties": {"p": subschema}}
        projection = AudienceProjection(choice_labels={"p": labels})
        return annotate(schema, projection)["properties"]["p"]

    def test_an_integer_spoken_whole_is_a_string(self) -> None:
        assert self.spoken({"type": "integer", "oneOf": [{"const": 1, "title": "Low"}]}) == {
            "type": "string",
            "oneOf": [{"const": "Low"}],
        }

    def test_a_nullable_integer_keeps_its_null(self) -> None:
        subschema = {"type": ["integer", "null"], "oneOf": [{"const": 1}, {"const": None}]}

        assert self.spoken(subschema) == {
            "type": ["string", "null"],
            "oneOf": [{"const": "Low"}, {"const": None}],
        }

    def test_null_is_stated_last_wherever_it_was_listed(self) -> None:
        subschema = {"type": ["integer", "null"], "enum": [None, 1]}

        assert self.spoken(subschema) == {"type": ["string", "null"], "enum": [None, "Low"]}

    def test_a_value_left_unspoken_keeps_its_type_beside_the_string(self) -> None:
        subschema = {"type": "integer", "enum": [1, 2]}

        assert self.spoken(subschema) == {"type": ["string", "integer"], "enum": ["Low", 2]}

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(True, "boolean"), (2.5, "number"), (3, "integer"), ("x", "string")],
    )
    def test_each_json_type_is_named_as_json_names_it(self, value: Any, expected: str) -> None:
        subschema = {"type": "string", "enum": [value]}

        assert self.spoken(subschema, {"other": "Other"})["type"] == expected

    def test_a_value_json_has_no_scalar_type_for_leaves_the_type_as_stated(self) -> None:
        """Only a type it can name is restated; anything else is left as written."""
        subschema = {"type": "array", "enum": [(1, 2)]}

        assert self.spoken(subschema) == subschema

    def test_a_one_of_with_no_constant_keeps_its_type(self) -> None:
        subschema = {"type": "string", "oneOf": [{"pattern": "^a"}]}

        assert self.spoken(subschema) == subschema

    def test_an_untyped_choice_states_no_type(self) -> None:
        """Nothing was claimed, so there is nothing to contradict."""
        assert self.spoken({"enum": [1]}) == {"enum": ["Low"]}
