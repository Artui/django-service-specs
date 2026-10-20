from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from django_service_specs.output.annotate_output_schema import annotate_output_schema
from django_service_specs.output.audience_projection import AudienceProjection
from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.output.output import Output, OutputField
from django_service_specs.output.project_payload import project_payload
from django_service_specs.schema.output_schema import output_schema
from django_service_specs.types.field_audience import FieldAudience
from django_service_specs.types.value_formatter import ValueFormatter
from tests.dispatch.test_audience_projection_for_spec import of
from tests.output.test_project_payload import invoice_projection
from tests.output.utils import HANDLE_DESCRIPTION, INVOICE, PROJECTED_SCHEMA

LABELS = {"PENDING_REVIEW": "Awaiting review", 1: "Low"}
HIDDEN_ETAG = AudienceProjection(fields={"etag": FieldMarking.hidden()})
TIMESTAMP = ValueFormatter.timestamp()
LOCAL_TIME = {"examples": ["31 Jan 2026 14:05"], "type": "string"}


def annotate(schema: dict[str, Any], projection: AudienceProjection, **kwargs: Any) -> Any:
    return annotate_output_schema(schema, projection, **kwargs)


def spoken(subschema: dict[str, Any], labels: dict[Any, str] = LABELS) -> Any:
    """``subschema`` as a property whose choices ``labels`` speaks, annotated."""
    schema = {"type": "object", "properties": {"p": subschema}}
    projection = AudienceProjection(choice_labels={"p": labels})
    return annotate(schema, projection)["properties"]["p"]


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
    @pytest.mark.parametrize(
        ("subschema", "expected"),
        [
            pytest.param(
                {"type": "string", "enum": ["PENDING_REVIEW", "X"]},
                {"type": "string", "enum": ["Awaiting review", "X"]},
                id="enum",
            ),
            # The shape an ``X | None`` reaches a schema in from elsewhere: each
            # member is rewritten, and the null one passes through.
            pytest.param(
                {"anyOf": [{"enum": ["PENDING_REVIEW"]}, {"type": "null"}]},
                {"anyOf": [{"enum": ["Awaiting review"]}, {"type": "null"}]},
                id="union-member-by-member",
            ),
            pytest.param(
                {"oneOf": [{"const": "PENDING_REVIEW", "title": "x"}, {"type": "null"}]},
                {"oneOf": [{"const": "Awaiting review"}, {"type": "null"}]},
                id="one-of-member-with-no-constant-passes-through",
            ),
            pytest.param(
                {"oneOf": [{"type": "null"}, {"const": "PENDING_REVIEW", "title": "x"}]},
                {"oneOf": [{"type": "null"}, {"const": "Awaiting review"}]},
                id="one-of-member-with-no-constant-keeps-its-place",
            ),
            pytest.param({"type": "string"}, {"type": "string"}, id="no-choice-keyword"),
        ],
    )
    def test_a_choice_schema_is_restated_in_its_displays(
        self, subschema: dict[str, Any], expected: dict[str, Any]
    ) -> None:
        assert spoken(subschema) == expected

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


class TestRestatedType:
    """A display is a string, so a stated type follows the values it now describes.

    Left as it was, an integer choice spoken as ``"Low"`` is described as an
    integer, and the projected payload fails the projected schema.
    """

    def test_an_integer_spoken_whole_is_a_string(self) -> None:
        assert spoken({"type": "integer", "oneOf": [{"const": 1, "title": "Low"}]}) == {
            "type": "string",
            "oneOf": [{"const": "Low"}],
        }

    def test_a_nullable_integer_keeps_its_null(self) -> None:
        subschema = {"type": ["integer", "null"], "oneOf": [{"const": 1}, {"const": None}]}

        assert spoken(subschema) == {
            "type": ["string", "null"],
            "oneOf": [{"const": "Low"}, {"const": None}],
        }

    def test_null_is_stated_last_wherever_it_was_listed(self) -> None:
        subschema = {"type": ["null", "integer"], "enum": [None, 1]}

        assert spoken(subschema) == {"type": ["string", "null"], "enum": [None, "Low"]}

    def test_null_is_kept_where_the_stated_type_admitted_it(self) -> None:
        """Here the null is admitted by an entry with no constant rather than
        listed as one, and it is still served, so the restated type must not
        refuse it."""
        subschema = {
            "type": ["integer", "null"],
            "oneOf": [{"const": 1, "title": "Low"}, {"type": "null"}],
        }

        assert spoken(subschema)["type"] == ["string", "null"]

    def test_a_null_spoken_as_a_label_is_not_named(self) -> None:
        """Django's ``(None, "Unknown")``: the stated type admitted a null, and
        the payload serves ``"Unknown"`` in its place, so the restated type
        names no null it never serves."""
        subschema = {
            "type": ["integer", "null"],
            "oneOf": [{"const": 1, "title": "Low"}, {"const": None, "title": "Unknown"}],
        }

        assert spoken(subschema, {**LABELS, None: "Unknown"}) == {
            "type": "string",
            "oneOf": [{"const": "Low"}, {"const": "Unknown"}],
        }

    def test_a_type_stated_as_null_alone_still_admits_it(self) -> None:
        """A scalar ``"null"`` is a stated type admitting null, as a list
        naming it is."""
        subschema = {"type": "null", "enum": [None, 1]}

        assert spoken(subschema) == {"type": ["string", "null"], "enum": [None, "Low"]}

    def test_a_type_that_refused_null_still_refuses_it(self) -> None:
        """The restated type admits what the stated one did, in display terms,
        and nothing more: a ``None`` the type refused was never served."""
        subschema = {"type": "integer", "enum": [1, None]}

        assert spoken(subschema) == {"type": "string", "enum": ["Low", None]}

    def test_a_value_left_unspoken_keeps_its_type_beside_the_string(self) -> None:
        subschema = {"type": "integer", "enum": [1, 2]}

        assert spoken(subschema) == {"type": ["string", "integer"], "enum": ["Low", 2]}

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(True, "boolean"), (2.5, "number"), (3, "integer"), ("x", "string")],
    )
    def test_each_json_type_is_named_as_json_names_it(self, value: Any, expected: str) -> None:
        subschema = {"type": "string", "enum": [value]}

        assert spoken(subschema, {"other": "Other"})["type"] == expected

    def test_a_value_json_has_no_scalar_type_for_leaves_the_type_as_stated(self) -> None:
        """Only a type it can name is restated; anything else is left as written."""
        subschema = {"type": "array", "enum": [(1, 2)]}

        assert spoken(subschema) == subschema

    def test_only_a_null_left_to_type_leaves_the_type_as_stated(self) -> None:
        """Nothing but ``None`` is listed and the stated type refused it, so
        there is no type to restate it as."""
        subschema = {"type": "integer", "enum": [None]}

        assert spoken(subschema) == subschema

    def test_a_one_of_with_no_constant_keeps_its_type(self) -> None:
        subschema = {"type": ["string", "null"], "oneOf": [{"pattern": "^a"}]}

        assert spoken(subschema) == subschema

    def test_a_choice_listing_nothing_keeps_its_type(self) -> None:
        """Nothing listed to restate the type from. Nullable, so that restating
        it from nothing would leave ``"null"`` alone in place of the type."""
        subschema = {"type": ["string", "null"], "enum": []}

        assert spoken(subschema) == subschema

    def test_an_entry_admitting_more_than_its_constants_keeps_the_type(self) -> None:
        """An entry with no ``const`` admits values the displays say nothing
        about, so narrowing the type to the displays' would refuse them: ``7``
        matches ``minimum`` and is an integer, and narrowed to ``"string"``
        the type would no longer admit it. Left as written, the type refuses
        the display ``"Low"`` a row holding ``1`` is served, so that row still
        fails this schema; only a schema written by hand reaches this shape,
        and narrowing would refuse ``7`` and the null as well."""
        subschema = {
            "type": ["integer", "null"],
            "oneOf": [{"const": 1, "title": "Low"}, {"minimum": 5}],
        }

        assert spoken(subschema) == {
            "type": ["integer", "null"],
            "oneOf": [{"const": "Low"}, {"minimum": 5}],
        }

    def test_an_untyped_choice_states_no_type(self) -> None:
        """Nothing was claimed, so there is nothing to contradict."""
        assert spoken({"enum": [1]}) == {"enum": ["Low"]}


class TestServedNull:
    """``"null"`` is named exactly where the projected payload can still serve one.

    A nullable field's ``None`` is served as its display where the choices give
    it one, and as a null where they do not.
    """

    @staticmethod
    def projected(choices: tuple[tuple[Any, str], ...]) -> tuple[Any, Any]:
        output = Output((OutputField("p", "integer", choices=choices, nullable=True),))
        projection = of(*output)
        schema = annotate(output_schema(output), projection)["properties"]["p"]
        return schema, project_payload({"p": None}, projection)["p"]

    def test_a_null_with_a_display_is_served_as_it_and_never_named(self) -> None:
        schema, served = self.projected(((None, "Unknown"), (1, "Low")))

        assert served == "Unknown"
        assert schema == {"type": "string", "oneOf": [{"const": "Unknown"}, {"const": "Low"}]}

    def test_a_null_with_no_display_is_served_and_still_named(self) -> None:
        schema, served = self.projected(((1, "Low"),))

        assert served is None
        assert schema == {"type": ["string", "null"], "oneOf": [{"const": "Low"}, {"const": None}]}


class TestSharedDisplays:
    """Django lets two values share one display, and a reader is told it once.

    Listed twice, a ``oneOf`` matches a row served that display under both
    entries, and ``oneOf`` admits only a value valid under exactly one, so
    every such row would fail the schema it is advertised under.
    """

    CHOICES = (("legacy", "Draft"), ("draft", "Draft"), ("live", "Published"))
    STAGE_LABELS: dict[Any, str] = dict(CHOICES)
    ARRAY_OF_STAGES: dict[str, Any] = {
        "type": "array",
        "items": {"enum": ["legacy", "draft"]},
        "uniqueItems": True,
    }

    def test_every_projected_row_matches_exactly_one_entry(self) -> None:
        output = Output((OutputField("status", "string", choices=self.CHOICES),))
        projection = of(*output)
        one_of = annotate(output_schema(output), projection)["properties"]["status"]["oneOf"]

        for value, _ in self.CHOICES:
            served = project_payload({"status": value}, projection)["status"]
            # ``oneOf`` of ``const`` entries as JSON Schema reads it: the row
            # is valid only if exactly one entry names its value.
            assert [entry for entry in one_of if entry.get("const") == served] == [
                {"const": served}
            ]
        assert one_of == [{"const": "Draft"}, {"const": "Published"}]

    def test_a_nullable_choice_keeps_its_null_once(self) -> None:
        output = Output(
            (OutputField("p", "integer", choices=((1, "Low"), (2, "Low")), nullable=True),)
        )

        assert annotate(output_schema(output), of(*output))["properties"]["p"] == {
            "type": ["string", "null"],
            "oneOf": [{"const": "Low"}, {"const": None}],
        }

    def test_an_enum_lists_each_display_once_in_first_seen_order(self) -> None:
        schema = {"type": "object", "properties": {"s": {"enum": ["live", "legacy", "draft"]}}}
        projection = AudienceProjection(
            choice_labels={"s": {"live": "Published", "legacy": "Draft", "draft": "Draft"}}
        )

        assert annotate(schema, projection)["properties"]["s"] == {"enum": ["Published", "Draft"]}

    def test_an_array_of_shared_displays_stops_claiming_unique_items(self) -> None:
        """``uniqueItems`` held for the stored values and not for their
        displays: two values selected together are served as one display
        twice, and the payload keeps both because both are selected."""
        schema = {"type": "object", "properties": {"s": self.ARRAY_OF_STAGES}}
        projection = AudienceProjection(choice_labels={"s": self.STAGE_LABELS})

        assert annotate(schema, projection)["properties"]["s"] == {
            "type": "array",
            "items": {"enum": ["Draft"]},
        }

    def test_an_array_of_distinct_displays_keeps_unique_items(self) -> None:
        """The condition of the drop: no two values collapsed, so the displays
        served for distinct values are distinct too."""
        subschema = {"type": "array", "items": {"enum": ["legacy", "live"]}, "uniqueItems": True}
        schema = {"type": "object", "properties": {"s": subschema}}
        projection = AudienceProjection(choice_labels={"s": self.STAGE_LABELS})

        assert annotate(schema, projection)["properties"]["s"] == {
            "type": "array",
            "items": {"enum": ["Draft", "Published"]},
            "uniqueItems": True,
        }

    def test_an_array_of_a_nullable_union_counts_across_its_members(self) -> None:
        """An element stated as ``anyOf`` lists its values in a member, and the
        collapse is counted there too."""
        subschema = {
            "type": "array",
            "items": {"anyOf": [{"enum": ["legacy", "draft"]}, {"type": "null"}]},
            "uniqueItems": True,
        }
        schema = {"type": "object", "properties": {"s": subschema}}
        projection = AudienceProjection(choice_labels={"s": self.STAGE_LABELS})

        assert "uniqueItems" not in annotate(schema, projection)["properties"]["s"]

    def test_two_selected_values_sharing_a_display_meet_their_schema(self) -> None:
        """End to end: ``["legacy", "draft"]`` is served as ``["Draft",
        "Draft"]``, and the schema it is advertised under admits that."""
        schema = {"type": "object", "properties": {"s": self.ARRAY_OF_STAGES}}
        projection = AudienceProjection(choice_labels={"s": self.STAGE_LABELS})
        served = project_payload({"s": ["legacy", "draft"]}, projection)["s"]
        stages = annotate(schema, projection)["properties"]["s"]

        assert served == ["Draft", "Draft"]
        assert all(item in stages["items"]["enum"] for item in served)
        # ``uniqueItems`` as JSON Schema reads it: a repeat fails the array.
        assert not stages.get("uniqueItems") or len(set(served)) == len(served)

    def test_a_boolean_is_not_the_number_python_says_it_equals(self) -> None:
        """The second condition of a repeat: ``True == 1`` in Python and not in
        JSON, so both stay listed and a row served either still matches."""
        schema = {"type": "object", "properties": {"s": {"enum": [True, 1, "x"]}}}
        projection = AudienceProjection(choice_labels={"s": {"x": "Ex"}})

        assert annotate(schema, projection)["properties"]["s"] == {"enum": [True, 1, "Ex"]}

    def test_a_boolean_and_the_number_it_equals_stay_two_constants(self) -> None:
        """The ``oneOf`` spelling of the test above, the one a duplicate would
        break: a row served ``1`` matches the entry naming ``1``."""
        subschema = {"oneOf": [{"const": True}, {"const": 1}, {"const": "x", "title": "Ex"}]}
        schema = {"type": "object", "properties": {"s": subschema}}
        projection = AudienceProjection(choice_labels={"s": {"x": "Ex"}})

        assert annotate(schema, projection)["properties"]["s"] == {
            "oneOf": [{"const": True}, {"const": 1}, {"const": "Ex"}]
        }


class TestFormatters:
    """A formatter replaces what the property said about its value."""

    @staticmethod
    def formatted(
        subschema: dict[str, Any],
        marking: FieldMarking | None = None,
        **projection: Any,
    ) -> Any:
        """``subschema`` as the property ``due``, annotated; formatted as a
        timestamp unless another marking is given."""
        fields = {"due": marking or FieldMarking.formatted(TIMESTAMP)}
        schema = {"type": "object", "properties": {"due": subschema}, "required": ["due"]}
        return annotate(schema, AudienceProjection(fields=fields, **projection))["properties"][
            "due"
        ]

    def test_a_formatted_field_is_described_as_what_it_produces(self) -> None:
        """A formatted local time is not the ``date-time`` the value was."""
        assert self.formatted({"type": "string", "format": "date-time"}) == LOCAL_TIME

    def test_a_title_and_a_description_survive(self) -> None:
        """Both annotate the field rather than its value."""
        subschema = {
            "type": "string",
            "format": "date-time",
            "title": "Due",
            "description": "When it is due.",
            "examples": ["2026-01-31T14:05:09Z"],
        }

        assert self.formatted(subschema) == {
            "title": "Due",
            "description": "When it is due.",
            **LOCAL_TIME,
        }

    def test_the_formatters_fragment_merges_over_what_is_carried(self) -> None:
        marking = FieldMarking.formatted(
            ValueFormatter(str, produces="string", schema={"title": "Due date"})
        )

        assert self.formatted({"type": "string", "title": "Due"}, marking) == {
            "title": "Due date",
            "type": "string",
        }

    def test_the_markings_description_still_wins(self) -> None:
        marking = FieldMarking.formatted(TIMESTAMP, "In the caller's zone.")

        assert self.formatted({"type": "string", "description": "UTC."}, marking) == {
            "description": "In the caller's zone.",
            **LOCAL_TIME,
        }

    def test_a_formatter_wins_over_the_choice_displays(self) -> None:
        """The mirror of the payload's order: no display is listed, and the
        type is the one the formatter produces rather than one restated from
        the displays."""
        subschema = {"type": "integer", "oneOf": [{"const": 1, "title": "Low"}]}
        marking = FieldMarking.formatted(ValueFormatter(str, produces="number"))

        assert self.formatted(subschema, marking, choice_labels={"due": {1: "Low"}}) == {
            "type": "number"
        }

    def test_the_formatters_own_values_are_not_spoken(self) -> None:
        """What the formatter declares is what it produces, so the displays of
        the stored values are never applied to it."""
        produced = ValueFormatter(str, produces="string", schema={"enum": ["a", "b"]})
        marking = FieldMarking.formatted(produced)

        assert self.formatted(
            {"type": "string", "enum": ["a", "b"]}, marking, choice_labels={"due": {"a": "Alpha"}}
        ) == {"type": "string", "enum": ["a", "b"]}

    def test_a_hidden_field_is_dropped_whatever_formats_it(self) -> None:
        """The schema's mirror of the payload test of that name: hidden is
        answered before the formatter is asked, so the property and its
        ``required`` entry both go."""
        schema = {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "due": {"type": "string"}},
            "required": ["id", "due"],
        }
        hidden = FieldMarking(FieldAudience.HIDDEN, formatter=TIMESTAMP)

        assert annotate(schema, AudienceProjection(fields={"due": hidden})) == {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
        }

    def test_a_formatter_replaces_a_nested_object(self) -> None:
        subschema = {"type": "object", "properties": {"cost": {"type": "string"}}}
        child = AudienceProjection(fields={"cost": FieldMarking.hidden()})

        assert self.formatted(subschema, nested={"due": child}) == LOCAL_TIME

    def test_a_handle_is_never_formatted(self) -> None:
        subschema = {"type": "string", "format": "date-time"}
        marking = FieldMarking(FieldAudience.HANDLE, formatter=TIMESTAMP)

        assert self.formatted(subschema, marking) == subschema

    @pytest.mark.parametrize(
        "subschema",
        [
            # A null is never formatted, so the projected payload still carries
            # one where the field allowed it.
            pytest.param({"type": ["string", "null"], "format": "date-time"}, id="type-list"),
            pytest.param({"type": "null"}, id="null-alone"),
            # The shape a dataclass field typed ``datetime | None`` is described
            # as: the null is a member of a union, not a word in a type.
            pytest.param(
                {"anyOf": [{"type": "string", "format": "date-time"}, {"type": "null"}]},
                id="any-of-member",
            ),
            # The shape ``ChoiceField(allow_null=True)`` is described as: untyped,
            # because its values are of two types, with the null among them.
            pytest.param({"enum": ["a", "b", None]}, id="enum"),
            # The enum lists the null the server serves, so it is read even
            # beside a type that does not name one.
            pytest.param({"type": "string", "enum": ["a", None]}, id="enum-beside-a-type"),
            pytest.param({"const": None}, id="const"),
            # A labelled nullable choice: the null is an entry of its own, as a
            # constant or as a type.
            pytest.param(
                {"oneOf": [{"const": "a", "title": "Alpha"}, {"const": None}]},
                id="one-of-const",
            ),
            pytest.param(
                {"oneOf": [{"const": "a", "title": "Alpha"}, {"type": "null"}]},
                id="one-of-type",
            ),
            # A member is read as a property is: its own type list, its own enum.
            pytest.param(
                {"anyOf": [{"type": ["string", "null"]}, {"type": "integer"}]},
                id="inside-an-any-of-member-type",
            ),
            pytest.param(
                {"anyOf": [{"enum": ["a", None]}, {"type": "integer"}]},
                id="inside-an-any-of-member-enum",
            ),
            # ``true`` and ``{}`` admit anything, null included.
            pytest.param({"anyOf": [{"type": "string"}, True]}, id="any-of-true"),
            pytest.param({"anyOf": [{"type": "string"}, {}]}, id="any-of-empty"),
            pytest.param({"oneOf": [{"type": "string"}, True]}, id="one-of-true"),
            pytest.param({"oneOf": [{"type": "string"}, {}]}, id="one-of-empty"),
        ],
    )
    def test_a_null_the_property_admits_stays_admitted(self, subschema: dict[str, Any]) -> None:
        assert self.formatted(subschema) == {**LOCAL_TIME, "type": ["string", "null"]}

    @pytest.mark.parametrize(
        "subschema",
        [
            # The negative of each spelling above.
            pytest.param({"type": ["string", "integer"]}, id="type-list"),
            pytest.param({"anyOf": [{"type": "string"}, {"type": "integer"}]}, id="any-of"),
            pytest.param({"oneOf": [{"const": "a"}, {"const": "b"}]}, id="one-of"),
            pytest.param({"enum": ["a", "b"]}, id="enum"),
            pytest.param({"type": "string", "const": "a"}, id="const"),
            # ``false`` admits nothing, and an entry that is no schema at all is
            # not read.
            pytest.param({"anyOf": [{"type": "string"}, False]}, id="any-of-false"),
            pytest.param({"anyOf": [{"type": "string"}, "string"]}, id="any-of-no-schema"),
            pytest.param({"oneOf": [{"type": "string"}, False]}, id="one-of-false"),
            pytest.param({"oneOf": [{"type": "string"}, "string"]}, id="one-of-no-schema"),
        ],
    )
    def test_a_property_admitting_no_null_admits_none_after_formatting(
        self, subschema: dict[str, Any]
    ) -> None:
        assert self.formatted(subschema) == LOCAL_TIME

    def test_a_schema_stating_nothing_about_its_value_still_admits_null(self) -> None:
        """An ``any`` field is described as ``{}``, which admits every value and
        the null with it, so a formatter over one keeps serving the null it
        passes through unformatted. A title says nothing about the value."""
        for subschema in ({}, {"title": "Extra"}):
            assert self.formatted(subschema)["type"] == ["string", "null"]

    @pytest.mark.parametrize(
        "keyword",
        [
            "title",
            "description",
            "examples",
            "default",
            "$comment",
            "deprecated",
            "readOnly",
            "writeOnly",
        ],
    )
    def test_an_annotation_alone_states_nothing_about_the_value(self, keyword: str) -> None:
        """Each annotation keyword describes the field, not its value, so a
        schema carrying only it still admits the null an ``any`` field passes."""
        assert self.formatted({keyword: "x"})["type"] == ["string", "null"]

    @pytest.mark.parametrize(
        "subschema",
        [
            {"$ref": "#/$defs/Status"},
            {"allOf": [{"$ref": "#/$defs/Status"}], "description": "s"},
            {"not": {"type": "null"}},
            {"properties": {"a": {"type": "string"}}, "required": ["a"]},
            {"format": "date-time"},
            {"items": {"type": "string"}},
            {"anyOf": [{"$ref": "#/$defs/A"}, {"$ref": "#/$defs/B"}]},
        ],
        ids=["ref", "allOf", "not", "properties", "format", "items", "anyOf-of-refs"],
    )
    def test_a_schema_stating_its_value_another_way_admits_no_null(
        self, subschema: dict[str, Any]
    ) -> None:
        """A reference, a composition, a negation or a shape says something
        about the value, so only the spellings above admit a null: a formatter
        over one serves a string, as it did before ``any`` existed."""
        assert self.formatted(subschema)["type"] == "string"

    @pytest.mark.parametrize(
        ("declared", "subschema", "expected"),
        [
            # The type now admits a null, so an ``enum`` the formatter lists
            # beside it must too, or the schema would refuse the null it just
            # admitted.
            pytest.param(
                {"enum": ("a", "b")},
                {"type": ["string", "null"]},
                {"enum": ["a", "b", None], "type": ["string", "null"]},
                id="enum",
            ),
            pytest.param(
                {"enum": ["a", None]},
                {"type": ["string", "null"]},
                {"enum": ["a", None], "type": ["string", "null"]},
                id="enum-already-listing-none",
            ),
            pytest.param(
                {"enum": ["a", "b"]},
                {"type": "string"},
                {"enum": ["a", "b"], "type": "string"},
                id="enum-on-a-field-admitting-no-null",
            ),
            # A ``const`` is a one-value ``enum``: restated as the ``enum`` of
            # that value and a null, the smallest statement that still admits
            # both.
            pytest.param(
                {"const": "n/a"},
                {"type": ["string", "null"]},
                {"enum": ["n/a", None], "type": ["string", "null"]},
                id="const",
            ),
            # Both must hold, so the values left are the constant alone.
            pytest.param(
                {"const": "a", "enum": ["a", "b"]},
                {"type": ["string", "null"]},
                {"enum": ["a", None], "type": ["string", "null"]},
                id="const-and-enum",
            ),
            pytest.param(
                {"const": None},
                {"type": ["string", "null"]},
                {"const": None, "type": ["string", "null"]},
                id="const-none",
            ),
            pytest.param(
                {"const": "a"},
                {"type": "string"},
                {"const": "a", "type": "string"},
                id="const-on-a-field-admitting-no-null",
            ),
        ],
    )
    def test_a_formatters_own_values_admit_the_null_its_field_does(
        self, declared: dict[str, Any], subschema: dict[str, Any], expected: dict[str, Any]
    ) -> None:
        produced = ValueFormatter(str, produces="string", schema=deepcopy(declared))

        assert self.formatted(subschema, FieldMarking.formatted(produced)) == expected
        # The declaration itself is never modified.
        assert produced.schema == declared

    def test_every_projected_row_meets_the_projected_schema(self) -> None:
        field = OutputField(
            "due", "string", format="date-time", nullable=True, marking=FieldMarking.timestamp()
        )
        output = Output((field,))
        projection = of(field)
        due = annotate(output_schema(output), projection)["properties"]["due"]
        json_type = {str: "string", type(None): "null"}

        for value in ("2026-01-31T14:05:09", None):
            served = project_payload({"due": value}, projection)["due"]
            assert json_type[type(served)] in due["type"]
