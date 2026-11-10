from __future__ import annotations

from typing import Any

from django_service_specs.output.output import Output, OutputField
from django_service_specs.schema.utils import allow_null, with_schema_extra
from django_service_specs.types.utils import is_json_native


def output_schema(output: Output) -> dict[str, Any]:
    """The JSON Schema object of one presented item, read from ``output``."""
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {field.name: _field_schema(field) for field in output},
    }
    required = [field.name for field in output if field.always_present]
    if required:
        schema["required"] = required
    return schema


def _field_schema(field: OutputField) -> dict[str, Any]:
    schema: dict[str, Any]
    if field.type == "array":
        schema = {"type": "array", "items": _items_schema(field)}
    elif field.fields is not None:
        # Only an object carries ``fields``; ``OutputField`` refuses them elsewhere.
        schema = output_schema(field.fields)
    elif field.type == "any":
        schema = {}
    else:
        schema = {"type": field.type}
    if field.format is not None:
        schema["format"] = field.format
    if field.choices is not None and field.type != "array":
        schema.update(_choice_keywords(field.choices, nullable=field.nullable))
    if field.nullable:
        schema = allow_null(schema)
    if field.label is not None:
        schema["title"] = str(field.label)
    return with_schema_extra(schema, field.json_schema_extra)


def _items_schema(field: OutputField) -> dict[str, Any]:
    """An array's element: its nested item's object schema, its type, or ``{}`` for any value."""
    items = field.items
    schema: dict[str, Any]
    if isinstance(items, Output):
        schema = output_schema(items)
    elif items is None:
        schema = {}
    else:
        schema = {"type": items}
    if field.choices is not None:
        schema.update(_choice_keywords(field.choices, nullable=field.items_nullable))
    if field.items_nullable:
        schema = allow_null(schema)
    return schema


def _choice_keywords(choices: tuple[tuple[Any, str], ...], *, nullable: bool) -> dict[str, Any]:
    """``enum`` when the displays add nothing, ``oneOf`` with titles when they do."""
    pairs = [(value, str(display)) for value, display in choices]
    values = [value for value, _ in pairs]
    if not all(is_json_native(value) for value in values):
        return {}
    widen = nullable and None not in values
    if all(display == str(value) for value, display in pairs):
        return {"enum": [*values, None] if widen else values}
    one_of: list[dict[str, Any]] = [{"const": value, "title": display} for value, display in pairs]
    if widen:
        one_of.append({"const": None})
    return {"oneOf": one_of}
