from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from django_service_specs.output.audience_projection import AudienceProjection
from django_service_specs.types.field_audience import FieldAudience
from django_service_specs.types.value_formatter import ValueFormatter

_ANNOTATIONS: Final = frozenset(
    {
        "title",
        "description",
        "examples",
        "default",
        "$comment",
        "deprecated",
        "readOnly",
        "writeOnly",
    }
)
"""The keywords that describe a field rather than its value.

A schema carrying these alone - an ``any`` field is described so - states
nothing about its value and admits every value, the null with it. Anything
else, a ``$ref``, an ``allOf``, a ``not``, a ``format`` or a shape, says
something about the value, and only ``_admits_null``'s other spellings decide
whether a null is among it. Each keyword is held by a case of
test_an_annotation_alone_states_nothing_about_the_value, and the boundary by
test_a_schema_stating_its_value_another_way_admits_no_null.
"""

_CARRIED: Final = ("title", "description")
"""Keywords that survive a formatter replacing a property's schema.

Both annotate the field rather than asserting anything about its value, so
neither stops being true when the value is rendered differently.
"""

_SCALAR_TYPES: Final = ((bool, "boolean"), (int, "integer"), (float, "number"), (str, "string"))
"""JSON's name for each kind of value a choice can hold, ``bool`` before the
``int`` it subclasses. ``None`` is handled apart, because ``"null"`` is stated
last whatever position the value had."""


def annotate_output_schema(
    schema: dict[str, Any] | None,
    projection: AudienceProjection,
    *,
    handle_description: str | None = None,
) -> dict[str, Any] | None:
    """Apply to a schema the ``project_payload`` projection applies to the payload."""
    if schema is None or projection.is_empty():
        return schema
    return _annotate(schema, projection, handle_description)


def _annotate(
    schema: dict[str, Any], projection: AudienceProjection, handle_description: str | None
) -> dict[str, Any]:
    # A list schema wraps the item schema: project the items and keep the array.
    items = schema.get("items")
    if isinstance(items, dict):
        return {**schema, "items": _annotate(items, projection, handle_description)}
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return schema
    annotated: dict[str, Any] = {}
    for name, subschema in properties.items():
        audience = projection.audience(name)
        if audience is FieldAudience.HIDDEN:
            continue
        formatter = projection.formatter(name)
        child = projection.nested.get(name)
        if formatter is not None:
            resolved = _formatted_schema(subschema, formatter)
        else:
            resolved = (
                _annotate(subschema, child, handle_description) if child is not None else subschema
            )
            if audience is not FieldAudience.HANDLE and name in projection.choice_labels:
                resolved = _spoken_schema(resolved, projection.choice_labels[name])
        description = _description(projection, name, audience, handle_description)
        annotated[name] = {**resolved, "description": description} if description else resolved
    result: dict[str, Any] = {**schema, "properties": annotated}
    required = [name for name in schema.get("required", []) if name in annotated]
    if required:
        result["required"] = required
    else:
        result.pop("required", None)
    return result


def _formatted_schema(schema: dict[str, Any], formatter: ValueFormatter) -> dict[str, Any]:
    """Restate a property as what its formatter produces."""
    carried = {key: schema[key] for key in _CARRIED if key in schema}
    formatted = {**carried, **formatter.json_schema()}
    if _admits_null(schema):
        formatted["type"] = [formatted["type"], "null"]
        if formatted.get("const") is not None:
            formatted["enum"] = [formatted.pop("const")]
        if "enum" in formatted and None not in formatted["enum"]:
            formatted["enum"] = [*formatted["enum"], None]
    return formatted


def _admits_null(schema: dict[str, Any]) -> bool:
    """Whether ``schema`` states that it admits a ``null``, in any spelling."""
    stated = schema.get("type")
    return (
        schema.keys() <= _ANNOTATIONS
        or _states_null(stated)
        or None in schema.get("enum", ())
        or schema.get("const", ...) is None
        or any(
            _member_admits_null(member)
            for union in ("anyOf", "oneOf")
            for member in schema.get(union, ())
        )
    )


def _states_null(stated: Any) -> bool:
    """Whether a ``"type"`` names ``"null"``: in a list of types, or as the type alone."""
    return "null" in (stated if isinstance(stated, list) else [stated])


def _member_admits_null(member: Any) -> bool:
    """Whether one entry of an ``anyOf`` or ``oneOf`` admits a ``null``."""
    if isinstance(member, dict):
        return _admits_null(member)
    return member is True


def _spoken_schema(schema: dict[str, Any], labels: Mapping[Any, str]) -> dict[str, Any]:
    """Restate a choice schema in the displays the payload now carries."""
    items = schema.get("items")
    if isinstance(items, dict):
        spoken_items = _spoken_schema(items, labels)
        spoken = {**schema, "items": spoken_items}
        if _listed_count(spoken_items) < _listed_count(items):
            spoken.pop("uniqueItems", None)
        return spoken
    if "anyOf" in schema:
        return {**schema, "anyOf": [_spoken_schema(member, labels) for member in schema["anyOf"]]}
    if "enum" in schema:
        values: list[Any] = []
        for value in schema["enum"]:
            display = labels.get(value, value)
            if not _is_listed(display, values):
                values.append(display)
        return _retyped({**schema, "enum": values}, values)
    if "oneOf" in schema:
        one_of: list[Any] = []
        consts: list[Any] = []
        for entry in schema["oneOf"]:
            if "const" not in entry:
                one_of.append(entry)
                continue
            display = labels.get(entry["const"], entry["const"])
            if not _is_listed(display, consts):
                consts.append(display)
                one_of.append({"const": display})
        spoken = {**schema, "oneOf": one_of}
        if any("const" not in entry and entry.get("type") != "null" for entry in one_of):
            return spoken
        admits_null = any(entry.get("type") == "null" for entry in one_of)
        return _retyped(spoken, [*consts, None] if admits_null else consts)
    return schema


def _listed_count(schema: dict[str, Any]) -> int:
    """How many values a choice schema lists, across a union's members."""
    members: list[Any] = schema.get("anyOf", [schema])
    return sum(len(member.get("enum", ())) + len(member.get("oneOf", ())) for member in members)


def _is_listed(value: Any, listed: list[Any]) -> bool:
    """Whether ``value`` is already in ``listed``, as JSON Schema compares values."""
    return any(
        value == seen and isinstance(value, bool) is isinstance(seen, bool) for seen in listed
    )


def _retyped(schema: dict[str, Any], values: list[Any]) -> dict[str, Any]:
    """``schema`` with any stated ``"type"`` restated as the types of ``values``."""
    if "type" not in schema or not values:
        return schema
    names: list[str] = []
    for value in values:
        if value is None:
            continue
        name = next(
            (json_name for kind, json_name in _SCALAR_TYPES if isinstance(value, kind)), None
        )
        if name is None:
            return schema
        if name not in names:
            names.append(name)
    stated = schema["type"]
    if None in values and _states_null(stated):
        names.append("null")
    if not names:
        return schema
    return {**schema, "type": names[0] if len(names) == 1 else names}


def _description(
    projection: AudienceProjection,
    name: str,
    audience: FieldAudience,
    handle_description: str | None,
) -> str | None:
    # Handle wording applies to handles only, never to an unmarked field.
    marking = projection.fields.get(name)
    if marking is not None and marking.description:
        return marking.description
    return handle_description if audience is FieldAudience.HANDLE else None
