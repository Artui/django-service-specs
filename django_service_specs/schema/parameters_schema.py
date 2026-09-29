"""``parameters_schema`` - the JSON Schema of what an operation takes."""

from __future__ import annotations

from typing import Any

from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.schema.utils import allow_null, is_json_native
from django_service_specs.types.unset import UNSET
from django_service_specs.validation.unknown_arguments import UnknownArguments


def parameters_schema(
    parameters: Parameters,
    *,
    unknown_arguments: UnknownArguments = UnknownArguments.REJECT,
) -> dict[str, Any]:
    """The JSON Schema object an argument set must satisfy, read from ``parameters``.

    One dialect whichever library declared the parameters, because every
    adapter reads its library into [`Parameters`][django_service_specs.parameters.parameters.Parameters]
    and this reads only that. The policy is **precise**: never false, and not
    incomplete where the declaration knows. What it still leaves out is what a
    Parameter does not carry.

    - **An object** is ``{"type": "object", "properties": {...}}``, with
      ``"required"`` listing, in declaration order, the names the shape check
      refuses when absent - a required parameter with no declared default,
      since one with a default is not refused - and left out when there are none.
    - **``"additionalProperties": false`` is emitted under ``REJECT`` only**, and
      at exactly the levels [`check_arguments`][django_service_specs.parameters.check_arguments.check_arguments]
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
      that declares no ``items`` and accepts any element.
    - **A scalar** is ``{"type": t}`` with its ``"format"`` when it declares one.
      A decimal is therefore ``{"type": "string", "format": "decimal"}``: the
      form every decimal validator reads without a binary float's rounding.
      The shape check also accepts a JSON number, which this does not advertise.
    - **Nullable** makes the type ``[t, "null"]``, on objects and arrays too,
      and ``items_nullable`` does the same to an array's ``items``.
    - **Choices** are an ``"enum"`` beside the ``"type"`` the parameter
      declares. On an array they go on ``items``, because the shape check
      applies them to each element. A nullable parameter's enum gains ``None``
      when its choices do not list it, since an enum claims the whole set of
      accepted values. An array's items do so by ``items_nullable`` alone,
      whether or not the array itself may be null.
    - **A default** is emitted when one is declared and survives JSON encoding;
      a ``Decimal``, a date or a callable is left out rather than misstated. So
      is a choice set holding such a value, since listing only some of the
      accepted values would be false.
    - **``help``** becomes ``"description"``.

    Nothing else, deliberately. No ``title``, because a Parameter has no label.
    No ``$defs`` or ``$ref`` ever: most MCP clients refuse a schema with a
    reference in it, so every schema is flat and self-contained, however deep
    the declaration nests. No ``$schema`` key, which a transport adds if its
    wire wants one. And no bounds (``maxLength``, ``minimum``), which
    Parameters does not carry yet; the Validator enforces them.

    Every call builds a new schema, so a transport may add its own keys to the
    result without reaching the declaration or another transport's copy.
    Defaults and choice values are placed in it as declared, not copied.

    ``unknown_arguments`` accepts the policy's plain value as well, and a value
    that is neither raises ``ValueError`` here rather than quietly describing
    one policy or the other.
    """
    return _object_schema(parameters, UnknownArguments(unknown_arguments))


def _object_schema(parameters: Parameters, policy: UnknownArguments) -> dict[str, Any]:
    """One level the shape check walks with ``_check_object``: the top, a declared object, a row."""
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {param.name: _parameter_schema(param, policy) for param in parameters},
    }
    # The shape check's own condition for "refused when absent", so the schema
    # and the check cannot disagree about a required parameter with a default.
    # One branch to coverage, so each condition is held by its own test:
    # test_an_optional_parameter_is_not_required and
    # test_a_required_parameter_with_a_default_is_not_required.
    required = [param.name for param in parameters if param.required and param.default is UNSET]
    if required:
        schema["required"] = required
    if policy is UnknownArguments.REJECT:
        schema["additionalProperties"] = False
    return schema


def _parameter_schema(param: Parameter, policy: UnknownArguments) -> dict[str, Any]:
    schema: dict[str, Any]
    if param.type == "array":
        schema = {"type": "array", "items": _items_schema(param, policy)}
    elif param.fields is not None:
        # Only an object carries ``fields``; ``Parameter`` refuses them elsewhere.
        schema = _object_schema(param.fields, policy)
    else:
        schema = {"type": param.type}
    if param.format is not None:
        schema["format"] = param.format
    # An array's choices describe its elements, and ``_items_schema`` states them.
    # One branch to coverage, so each condition is held by its own test:
    # test_a_scalar_states_its_type (the first: a parameter with no choices) and
    # test_an_arrays_choices_constrain_each_item_and_not_the_array (the second).
    if param.choices is not None and param.type != "array":
        enum = _enum(param.choices, nullable=param.nullable)
        if enum is not None:
            schema["enum"] = enum
    if param.nullable:
        schema = allow_null(schema)
    # ``UNSET``, the declaration of no default, is not a JSON value either, so
    # this one test leaves out both a missing default and one JSON cannot carry.
    # A second ``is not UNSET`` conjunct would change nothing a test could see.
    # Held by test_a_parameter_with_no_default_states_none and
    # test_a_default_json_cannot_carry_is_left_out.
    if is_json_native(param.default):
        schema["default"] = param.default
    if param.help:
        # ``str()`` because an adapter may pass a lazy translation through, which
        # is not a JSON value: it is rendered in the language active now.
        schema["description"] = str(param.help)
    return schema


def _items_schema(param: Parameter, policy: UnknownArguments) -> dict[str, Any]:
    """An array's element: its rows' object schema, its type, or ``{}`` for any value."""
    items = param.items
    schema: dict[str, Any]
    if isinstance(items, Parameters):
        schema = _object_schema(items, policy)
    elif items is None:
        schema = {}
    else:
        schema = {"type": items}
    if param.choices is not None:
        # Widened with null by the element's nullability and never the array's:
        # the shape check keeps a null element only where ``items_nullable``
        # says so, and does so before it reads the choices. An untyped element
        # admits null only when the choices list it.
        enum = _enum(param.choices, nullable=param.items_nullable)
        if enum is not None:
            schema["enum"] = enum
    if param.items_nullable:
        # ``Parameter`` refuses ``items_nullable`` without ``items``, so the
        # element is typed and ``allow_null`` has a type to widen.
        schema = allow_null(schema)
    return schema


def _enum(choices: tuple[Any, ...], *, nullable: bool) -> list[Any] | None:
    """The accepted values, or ``None`` when one of them cannot be stated in JSON."""
    if not all(is_json_native(value) for value in choices):
        return None
    values = list(choices)
    # The shape check lets ``None`` through a nullable parameter before it reads
    # the choices, so an enum that did not list it would refuse a call that runs.
    if nullable and None not in values:
        values.append(None)
    return values
