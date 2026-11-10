from __future__ import annotations

from typing import Any

from django_service_specs.parameters.max_length_in_force import max_length_in_force
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.parameters.utils import unknown_arguments_policy
from django_service_specs.schema.utils import allow_null, with_schema_extra
from django_service_specs.types.unknown_arguments import UnknownArguments
from django_service_specs.types.unset import UNSET
from django_service_specs.types.utils import is_json_native


def parameters_schema(
    parameters: Parameters,
    *,
    unknown_arguments: UnknownArguments = UnknownArguments.REJECT,
) -> dict[str, Any]:
    """The JSON Schema object an argument set must satisfy, read from ``parameters``."""
    return _object_schema(parameters, unknown_arguments_policy(unknown_arguments))


def _object_schema(parameters: Parameters, policy: UnknownArguments) -> dict[str, Any]:
    """One level the shape check walks with ``_check_object``: the top, a declared object, a row."""
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {param.name: _parameter_schema(param, policy) for param in parameters},
    }
    required = [param.name for param in parameters if param.required and param.default is UNSET]
    if required:
        schema["required"] = required
    if policy is UnknownArguments.REJECT:
        schema["additionalProperties"] = False
    return schema


def _parameter_schema(param: Parameter, policy: UnknownArguments) -> dict[str, Any]:
    schema: dict[str, Any]
    if param.type == "array":
        schema = {"type": "array", "items": _items_schema(param, policy), **_lengths(param)}
    elif param.fields is not None:
        # Only an object carries ``fields``; ``Parameter`` refuses them elsewhere.
        schema = _object_schema(param.fields, policy)
    elif param.type in ("file", "any"):
        schema = {}
    else:
        schema = {"type": param.type}
    if param.type != "array":
        schema.update(_reading(param))
        if param.choices is not None:
            schema.update(_choices(param, nullable=param.nullable))
    if param.nullable:
        schema = allow_null(schema)
    if is_json_native(param.default):
        schema["default"] = param.default
    if param.help:
        schema["description"] = str(param.help)
    return with_schema_extra(schema, param.json_schema_extra)


def _reading(param: Parameter) -> dict[str, Any]:
    """The value's ``format`` and bounds: a scalar's own, or an array's element's."""
    reading: dict[str, Any] = {}
    if param.format is not None:
        reading["format"] = param.format
    if param.format == "decimal":
        return reading
    if param.minimum is not None:
        reading["minimum"] = param.minimum
    if param.maximum is not None:
        reading["maximum"] = param.maximum
    return reading


def _lengths(param: Parameter) -> dict[str, Any]:
    """An array's ``minItems`` as declared, and its ``maxItems`` as in force."""
    lengths: dict[str, Any] = {}
    if param.min_length is not None:
        lengths["minItems"] = param.min_length
    most = max_length_in_force(param)
    if most is not None:
        lengths["maxItems"] = most
    return lengths


def _items_schema(param: Parameter, policy: UnknownArguments) -> dict[str, Any]:
    """An array's element: its rows' object schema, its type, or ``{}`` for any value."""
    items = param.items
    schema: dict[str, Any]
    if isinstance(items, Parameters):
        schema = _object_schema(items, policy)
    elif items is None or items == "file":
        schema = {}
    else:
        schema = {"type": items, **_reading(param)}
    if param.choices is not None:
        schema.update(_choices(param, nullable=param.items_nullable))
    if param.items_nullable:
        schema = allow_null(schema)
    return schema


def _choices(param: Parameter, *, nullable: bool) -> dict[str, Any]:
    """The ``enum`` or ``anyOf`` schema for the accepted values, or ``{}`` if none is stated."""
    choices = param.choices or ()
    if not all(is_json_native(value) for value in choices):
        return {}
    labels = param.choice_labels or ()
    if not any(str(label) != str(value) for value, label in labels):
        values = list(choices)
        if nullable and None not in values:
            values.append(None)
        return {"enum": values}
    listed: list[Any] = []
    entries: list[dict[str, Any]] = []
    for value in choices:
        if any(_same(value, seen) for seen in listed):
            continue
        listed.append(value)
        entry: dict[str, Any] = {"type": "null"} if value is None else {"const": value}
        label = next((label for known, label in labels if _same(known, value)), None)
        if label is not None:
            entry["title"] = str(label)
        entries.append(entry)
    if nullable and None not in choices:
        entries.append({"type": "null"})
    return {"anyOf": entries}


def _same(one: Any, other: Any) -> bool:
    """Whether two choices are one JSON value: Python's equality, with ``True`` apart from ``1``."""
    return one == other and isinstance(one, bool) == isinstance(other, bool)
