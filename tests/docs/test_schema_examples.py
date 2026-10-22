"""The JSON Schema page's example, run.

The page shows what each call in ``docs/examples/schema.py`` returns. The
assertions here are those statements, and the page's JSON blocks are read
back and compared with them, so neither the page nor the emitter can drift
from the other.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs import (
    OutputField,
    Parameter,
    Parameters,
    check_arguments,
    dispatch,
    present,
)
from django_service_specs.types.utils import OUTPUT_FIELD_SCHEMA_KEYWORDS, PARAMETER_SCHEMA_KEYWORDS
from docs.examples import schema
from tests.dispatch.utils import make_user
from tests.dispatch_app.models import Note

ROOT = Path(__file__).resolve().parents[2]

NOTES_INPUT = {
    "type": "object",
    "properties": {
        "search": {"type": "string", "description": "Part of the title, in any case."},
        "ordering": {"type": "string", "enum": ["title", "-title"], "default": "title"},
    },
    "additionalProperties": False,
}

NOTES_OUTPUT = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "title": {"type": "string"}},
        "required": ["id", "title"],
    },
}

BOOK_IN = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "price": {"type": "string", "format": "decimal"},
        "status": {
            "type": "string",
            "anyOf": [
                {"const": "draft", "title": "Draft"},
                {"const": "published", "title": "Published"},
            ],
            "default": "draft",
        },
        "published_on": {"type": ["string", "null"], "format": "date", "default": None},
        "pk": {"type": ["integer", "null"], "default": None},
    },
    "required": ["title", "price"],
    "additionalProperties": False,
}

AUTHOR_INPUT = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "books": {"type": "array", "items": BOOK_IN, "maxItems": 1000},
    },
    "required": ["name"],
    "additionalProperties": False,
}

AUTHOR_OUTPUT = {
    "type": ["object", "null"],
    "properties": {
        "id": {"type": "integer"},
        "name": {"type": "string"},
        "books": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "title": {"type": "string"},
                    "price": {"type": "string", "format": "decimal"},
                    "status": {
                        "type": "string",
                        "oneOf": [
                            {"const": "draft", "title": "Draft"},
                            {"const": "published", "title": "Published"},
                        ],
                    },
                },
                "required": ["id", "title", "price", "status"],
            },
        },
    },
    "required": ["id", "name", "books"],
}


def without_closing(node: Any) -> Any:
    """``node`` with every ``additionalProperties`` removed, however deep."""
    if isinstance(node, dict):
        return {k: without_closing(v) for k, v in node.items() if k != "additionalProperties"}
    return node


class TestSchemaPage:
    def test_the_notes_list_takes_its_reads_and_refuses_anything_else(self) -> None:
        assert schema.notes_input == NOTES_INPUT

    def test_the_notes_list_returns_an_array_of_rows_with_no_markings_stated(self) -> None:
        assert schema.notes_output == NOTES_OUTPUT

    def test_the_author_write_describes_and_closes_each_row(self) -> None:
        assert schema.author_input == AUTHOR_INPUT

    def test_the_lenient_author_write_is_the_same_with_nothing_closed(self) -> None:
        assert schema.lenient_author_input == without_closing(AUTHOR_INPUT)
        assert schema.lenient_author_input != AUTHOR_INPUT

    def test_the_author_write_may_return_null_and_titles_each_status(self) -> None:
        assert schema.author_output == AUTHOR_OUTPUT

    def test_a_service_allowing_none_admits_null_beside_its_row(self) -> None:
        assert schema.archive_output == {**NOTES_OUTPUT["items"], "type": ["object", "null"]}
        assert schema.archive_oldest_spec.allow_none is True

    @pytest.mark.django_db
    def test_the_archive_presents_its_row_and_then_nothing(self) -> None:
        """What the declared null is for: the second call has nothing left."""
        ada = make_user("ada")
        note = Note.objects.create(owner=ada, title="Draft")
        spec = schema.archive_oldest_spec

        first = present(spec, dispatch(spec, principal=ada, arguments={}))
        second = present(spec, dispatch(spec, principal=ada, arguments={}))

        assert (first, second) == ({"id": note.pk, "title": "Draft"}, None)

    def test_the_pages_json_blocks_are_what_the_example_returns(self) -> None:
        page = (ROOT / "docs" / "schema.md").read_text()
        blocks = [json.loads(b) for b in re.findall(r"```json\n(.*?)```", page, re.DOTALL)]

        assert blocks == [
            NOTES_INPUT,
            NOTES_OUTPUT,
            AUTHOR_INPUT,
            AUTHOR_OUTPUT,
            schema.isbn_input,
            schema.tags_output,
        ]


class TestJsonSchemaExtra:
    def test_each_node_carries_the_keywords_as_written(self) -> None:
        assert schema.isbn_input == {
            "type": "object",
            "properties": {
                "isbn": {
                    "type": "string",
                    "description": "The 13-digit ISBN, digits only.",
                    "pattern": "^97[89][0-9]{10}$",
                    "maxLength": 13,
                }
            },
            "additionalProperties": False,
        }
        assert schema.tags_output == {
            "type": "object",
            "properties": {
                "tags": {"type": "array", "items": {"type": "string"}, "uniqueItems": True}
            },
            "required": ["tags"],
        }

    @pytest.mark.parametrize(
        ("row", "keywords"),
        [
            ("`Parameter`", PARAMETER_SCHEMA_KEYWORDS),
            ("`OutputField`", OUTPUT_FIELD_SCHEMA_KEYWORDS),
        ],
    )
    def test_the_page_s_tables_list_every_keyword_refused_and_no_other(
        self, row: str, keywords: Any
    ) -> None:
        page = (ROOT / "docs" / "schema.md").read_text()
        (cell,) = re.findall(rf"^\| {re.escape(row)} \| (.*) \|$", page, re.MULTILINE)
        assert set(re.findall(r"`(\w+)`", cell)) == set(keywords)

    def test_it_is_advertised_and_not_enforced_by_the_shape_check(self) -> None:
        checked = check_arguments(Parameters.of(schema.isbn), {"isbn": "not an isbn"})
        assert checked == {"isbn": "not an isbn"}

    @pytest.mark.parametrize(
        ("build", "named"),
        [
            (lambda: Parameter("isbn", "string", json_schema_extra={"format": "isbn"}), "format"),
            (lambda: Parameter("n", "integer", json_schema_extra={"maximum": 3}), "maximum"),
            (lambda: OutputField("t", "string", json_schema_extra={"title": "T"}), "label"),
        ],
    )
    def test_a_keyword_a_field_states_is_refused_naming_the_field(
        self, build: Any, named: str
    ) -> None:
        with pytest.raises(ImproperlyConfigured, match=f"takes from {named}"):
            build()

    def test_a_value_json_cannot_carry_is_refused(self) -> None:
        with pytest.raises(ImproperlyConfigured, match=r"json_schema_extra\['examples'\]"):
            Parameter("price", "string", json_schema_extra={"examples": [Decimal("9.99")]})

    def test_it_is_held_as_a_copy(self) -> None:
        extra: dict[str, Any] = {"examples": [["a"]]}
        param = Parameter("tags", "array", items="string", json_schema_extra=extra)
        extra["examples"][0].append("b")
        assert param.json_schema_extra == {"examples": [["a"]]}
