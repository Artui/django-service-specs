from __future__ import annotations

from typing import Any

import pytest

from django_service_specs.output.output import OutputField
from django_service_specs.parameters.parameters import Parameter
from django_service_specs.schema.fragment_keywords import fragment_keywords


@pytest.mark.parametrize(
    ("fragment", "keywords"),
    [
        ({"type": "string"}, {"type": "string"}),
        ({"type": ["integer", "null"]}, {"type": "integer", "nullable": True}),
        ({"type": ["integer", "string"]}, {"type": "any"}),
        ({"type": ["integer", "string", "null"]}, {"type": "any"}),
        ({}, {"type": "any"}),
        ({"type": "decimal"}, {"type": "any"}),
        ({"enum": [1, 2]}, {"type": "integer", "choices": (1, 2)}),
        ({"enum": [1, "a"]}, {"type": "any"}),
        ({"type": "number", "enum": [1, 2]}, {"type": "number", "choices": (1, 2)}),
        ({"type": "string", "format": "date"}, {"type": "string", "format": "date"}),
        ({"type": "string", "format": "money"}, {"type": "string"}),
        ({"type": "array", "items": {"type": "integer"}}, {"type": "array", "items": "integer"}),
        ({"type": "array", "items": {"type": "integer", "minimum": 0}}, {"type": "array"}),
        ({"type": "array", "items": {"type": "money"}}, {"type": "array"}),
        ({"type": "array", "items": {"type": ["string", "null"]}}, {"type": "array"}),
        (
            {"type": "integer", "minimum": 1, "maximum": 9},
            {"type": "integer", "minimum": 1, "maximum": 9},
        ),
        (
            {"type": "array", "minItems": 1, "maxItems": 3},
            {"type": "array", "min_length": 1, "max_length": 3},
        ),
        ({"type": "string", "description": "A code."}, {"type": "string", "help": "A code."}),
        (
            {"type": "string", "pattern": "^A"},
            {"type": "string", "json_schema_extra": {"pattern": "^A"}},
        ),
    ],
)
def test_a_fragment_as_a_parameter_s_keywords(
    fragment: dict[str, Any], keywords: dict[str, Any]
) -> None:
    assert fragment_keywords(fragment) == keywords
    Parameter("code", **keywords)


@pytest.mark.parametrize(
    ("fragment", "keywords"),
    [
        ({"type": "string", "title": "Code"}, {"type": "string", "label": "Code"}),
        ({"enum": ["a", "b"]}, {"type": "string", "choices": (("a", "a"), ("b", "b"))}),
        (
            {"type": "integer", "minimum": 1},
            {"type": "integer", "json_schema_extra": {"minimum": 1}},
        ),
    ],
)
def test_a_fragment_as_an_output_field_s_keywords(
    fragment: dict[str, Any], keywords: dict[str, Any]
) -> None:
    assert fragment_keywords(fragment, output=True) == keywords
    OutputField("code", **keywords)
