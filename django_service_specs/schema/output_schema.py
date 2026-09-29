"""``output_schema`` - the JSON Schema of one item an operation returns."""

from __future__ import annotations

from typing import Any

from django_service_specs.output.output import Output
from django_service_specs.output.output_field import OutputField
from django_service_specs.schema.utils import allow_null, is_json_native


def output_schema(output: Output) -> dict[str, Any]:
    """The JSON Schema object of one presented item, read from ``output``.

    One item: whether the operation returns a list of them, or may return
    ``None`` instead, is the spec's to say, and
    [`spec_output_schema`][django_service_specs.schema.spec_output_schema.spec_output_schema]
    wraps this accordingly. The dialect is the input side's, with the
    differences a description of what came back needs:

    - **An object** is ``{"type": "object", "properties": {...}}``, with
      ``"required"`` listing the fields whose ``always_present`` is true, in
      declaration order, and left out when there are none. ``required`` says
      the key is there, not that its value is non-null.
    - **No ``additionalProperties``.** Output is not a closed set a caller can
      get wrong, and a transport may add keys of its own to what it sends.
    - **A field** states its type, ``[t, "null"]`` when nullable, its
      ``"format"`` when it declares one, and ``"title"`` from its ``label``
      when it has one. Adapters set a label only where the author wrote one,
      so a title is never a field name restated in worse English.
    - **Nesting** is as on input: ``fields`` make an object schema, an
      object with none is ``{"type": "object"}``, and an array's ``items`` are
      ``{"type": t}``, a nested item's object schema, or ``{}`` when undeclared.
      ``items_nullable`` makes the item's type ``[t, "null"]``.
    - **Choices** are ``(value, display)`` pairs. When every display is just
      ``str(value)`` they are an ``"enum"`` of the values, since a title
      restating the constant teaches nothing. Otherwise they are a ``"oneOf"``
      of ``{"const": value, "title": display}``, so the human phrasing travels
      with each value; ``title`` constrains nothing, and the accepted set stays
      exactly the constants. The ``"type"`` is stated either way. A nullable
      field adds ``None`` (``{"const": None}`` in a ``oneOf``) when its choices
      do not list it, because both forms claim the whole set of values. On an
      array the choices describe each element and go on ``items``, widened
      by ``items_nullable`` rather than the array's own nullability. A choice
      set holding a value JSON cannot carry is left out whole.

    ``marking`` is **not** emitted. Showing a field to an agent audience, or
    leaving it out, is a projection over this schema, and projection is not
    the kernel's yet; the kernel declares a marking and applies none, which is
    why a ``HIDDEN`` field is described here like any other.

    As on input: no ``$defs`` or ``$ref``, no ``$schema`` key, and a new
    schema on every call.
    """
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
    else:
        schema = {"type": field.type}
    if field.format is not None:
        schema["format"] = field.format
    # An array's choices describe its elements, and ``_items_schema`` states them.
    # One branch to coverage, so each condition is held by its own test:
    # test_a_scalar_states_its_type (the first: a field with no choices) and
    # test_an_arrays_choices_describe_each_item_and_not_the_array (the second).
    if field.choices is not None and field.type != "array":
        schema.update(_choice_keywords(field.choices, nullable=field.nullable))
    if field.nullable:
        schema = allow_null(schema)
    if field.label is not None:
        # ``str()`` because a label may be a lazy translation, which is not a JSON
        # value: it is rendered in the language active when the schema is built.
        schema["title"] = str(field.label)
    return schema


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
        # Widened with null by the element's nullability, never the array's,
        # which describes the array.
        schema.update(_choice_keywords(field.choices, nullable=field.items_nullable))
    if field.items_nullable:
        # ``OutputField`` refuses ``items_nullable`` without ``items``, so the
        # element is typed and ``allow_null`` has a type to widen.
        schema = allow_null(schema)
    return schema


def _choice_keywords(choices: tuple[tuple[Any, str], ...], *, nullable: bool) -> dict[str, Any]:
    """``enum`` when the displays add nothing, ``oneOf`` with titles when they do."""
    # ``str(display)`` for a lazy translation, as for a label.
    pairs = [(value, str(display)) for value, display in choices]
    values = [value for value, _ in pairs]
    if not all(is_json_native(value) for value in values):
        return {}
    # Only when absent: a second ``{"const": None}`` would make ``oneOf`` match a
    # null twice, which is a failure, so the widening meant to admit null would
    # refuse it.
    widen = nullable and None not in values
    if all(display == str(value) for value, display in pairs):
        return {"enum": [*values, None] if widen else values}
    one_of: list[dict[str, Any]] = [{"const": value, "title": display} for value, display in pairs]
    if widen:
        one_of.append({"const": None})
    return {"oneOf": one_of}
