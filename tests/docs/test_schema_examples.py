"""The JSON Schema page's example, run.

The page shows what each call in ``docs/examples/schema.py`` returns. The
assertions here are those statements, and the page's JSON blocks are read
back and compared with them, so neither the page nor the emitter can drift
from the other.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from docs.examples import schema

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
        "status": {"type": "string", "enum": ["draft", "published"], "default": "draft"},
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
        "books": {"type": "array", "items": BOOK_IN},
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

    def test_the_pages_json_blocks_are_what_the_example_returns(self) -> None:
        page = (ROOT / "docs" / "schema.md").read_text()
        blocks = [json.loads(b) for b in re.findall(r"```json\n(.*?)```", page, re.DOTALL)]

        assert blocks == [NOTES_INPUT, NOTES_OUTPUT, AUTHOR_INPUT, AUTHOR_OUTPUT]
