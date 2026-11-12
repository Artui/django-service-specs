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
    """The JSON Schema object an argument set must satisfy, read from ``parameters``.

    One dialect whichever library declared the parameters, because every
    adapter reads its library into
    [`Parameters`][django_service_specs.parameters.parameters.Parameters]
    and this reads only that. The policy is **precise**: never false, and not
    incomplete where the declaration knows. What it still leaves out is what a
    Parameter does not carry, and a decimal's bound, which JSON Schema has no
    way to state on a string.

    - **An object** is ``{"type": "object", "properties": {...}}``, with
      ``"required"`` listing, in declaration order, the names the shape check
      refuses when absent - a required parameter with no declared default,
      since one with a default is not refused - and left out when there are none.
    - **``"additionalProperties": false`` is emitted under ``REJECT`` only**, and
      at exactly the levels
      [`check_arguments`][django_service_specs.parameters.check_arguments.check_arguments]
      closes: the top, every object parameter that declares ``fields``, and
      every row of an array whose ``items`` are Parameters - an empty
      declaration included, since it refuses every key. Under ``IGNORE`` an
      undeclared key is accepted and dropped, so stating ``false`` there
      would refuse a call that runs.
    - **An object parameter with no ``fields``** is ``{"type": "object"}``: what
      is still known, constraining nothing a valid call could fail. It is also
      the node an adapter truncates a recursive declaration to.
    - **An array** is ``{"type": "array", "items": ...}``: a type name's
      ``{"type": t}``, the object schema of its rows, or ``{}`` for an array
      that declares no ``items`` and accepts any element. The array's
      ``format`` and bounds describe each element, so they go on ``items``,
      as its choices do: a CSV number filter's are ``{"type": "string",
      "format": "decimal"}``, and an array of ``integer`` bounded at 1 has
      ``{"type": "integer", "minimum": 1}``.
    - **A file** is ``{}``. No JSON value is one, so any JSON type stated here
      would be false, and JSON Schema has no keyword for a multipart part.
      What is still known is the rest: whether it is required, its
      ``"description"``. An array of files has ``{}`` for its items.
    - **An** ``any`` is ``{}`` too, since every JSON value is one; its
      ``"default"`` and ``"description"`` are stated as on any other node.
    - **A scalar** is ``{"type": t}`` with its ``"format"`` when it declares one.
      A decimal is therefore ``{"type": "string", "format": "decimal"}``: the
      form every decimal validator reads without a binary float's rounding.
      The shape check also accepts a JSON number, which this does not advertise.
      An identifier is ``{"type": "string", "format": "uuid"}``, JSON
      Schema's own format name, and the shape check refuses a string that
      spells no UUID.
    - **An array's length** is ``"minItems"`` as declared, and ``"maxItems"``
      as in force: the declared ``max_length``, or where none is declared the
      ``SERVICE_SPECS_MAX_ARRAY_LENGTH`` setting's, 1000 unless the project
      sets another. The shape check refuses past it either way, so a client
      told nothing would send a call that cannot run; under a setting of
      ``None`` an array that declares no maximum states none.
    - **Bounds** are ``"minimum"`` and ``"maximum"``, inclusive, as declared,
      on an ``integer`` and a ``number``. **A decimal string states neither**:
      JSON Schema applies them to a number instance only, so on a string a
      validating client ignores both and a strict one may flag them. The shape
      check still enforces them, as it does for every bound.
    - **Nullable** makes the type ``[t, "null"]``, on objects and arrays too,
      and ``items_nullable`` does the same to an array's ``items``. A file's
      node and an ``any``'s state no type, so they admit null already and
      gain nothing; a non-nullable one's ``null`` is refused by the shape
      check alone.
    - **Choices** are an ``"enum"`` beside the ``"type"`` the parameter
      declares. On an array they go on ``items``, because the shape check
      applies them to each element. A nullable parameter's enum gains ``None``
      when its choices do not list it, since an enum claims the whole set of
      accepted values. An array's items do so by ``items_nullable`` alone,
      whether or not the array itself may be null.
    - **Labelled choices** are an ``"anyOf"`` of ``{"const": value, "title":
      label}`` in its place, where some label says more than its value does;
      labels that only repeat their values keep the ``"enum"``. A choice with
      no label is a bare ``{"const": value}``. A ``None`` is ``{"type":
      "null"}`` instead, titled when it is labelled, and so is the ``None`` a
      nullable parameter gains. A choice declared twice is listed once, so
      the entries are disjoint and each value has one title; ``True`` and
      ``1`` are two values to JSON, although Python finds them equal.
      ``anyOf`` rather than ``oneOf``, which admits the same values over
      disjoint entries: an OpenAI strict schema refuses ``oneOf``, and Gemini
      refuses it too, where pydantic-ai rewrites it only on a node with no
      ``"type"``. And ``{"type": "null"}`` rather than ``{"const": null}``,
      which Google's transform empties into ``{}``, a schema every value
      matches. A title is ``str()`` of the label, so a lazy one is rendered in
      the language active now, and it constrains nothing.
    - **A default** is emitted when one is declared and survives JSON encoding;
      a ``Decimal``, a date or a callable is left out rather than misstated. So
      is a choice set holding such a value, since listing only some of the
      accepted values would be false.
    - **``help``** becomes ``"description"``.
    - **``json_schema_extra``** joins the parameter's node last, at any
      depth: the keywords the declaration has no field for, such as a
      ``pattern`` or a string's ``maxLength``. The Parameter refused every
      keyword a field states here when it was declared, a custom ``format``
      included, so the extra never restates or contradicts the declaration.
      What it states is advertised and not enforced by the shape check; it
      holds where the spec's Validator enforces it.

    Nothing else, deliberately. No ``title`` on a property, because a Parameter
    has no label of its own; a ``title`` is only ever a choice's.
    No ``$defs`` or ``$ref`` ever: most MCP clients refuse a schema with a
    reference in it, so every schema is flat and self-contained, however deep
    the declaration nests. No ``$schema`` key, which a transport adds if its
    wire wants one. And no bound the shape check does not enforce
    (``maxLength``, a Validator's ``max_value``) unless a ``json_schema_extra``
    states it, for a Validator that enforces it.
    The one stated without being declared is an array's default maximum,
    because the shape check enforces it. The one enforced without being
    stated is a decimal's bound, because a string has no keyword for it.

    Every call builds a new schema, so a transport may add its own keys to the
    result without reaching the declaration or another transport's copy.
    Defaults, choice values and ``json_schema_extra`` values are placed in it
    as declared, not copied.

    ``unknown_arguments`` accepts the policy's plain value as well, and a value
    that is neither, or the kept ``PASSTHROUGH`` member, raises ``ValueError``
    here rather than quietly describing one policy or the other.
    """
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
