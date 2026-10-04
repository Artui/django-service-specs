"""``annotate_output_schema`` - mirror an audience projection onto a JSON Schema."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from django_service_specs.output.audience_projection import AudienceProjection
from django_service_specs.output.field_audience import FieldAudience
from django_service_specs.types.value_formatter import ValueFormatter

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
    """Apply to a schema the projection [`project_payload`][django_service_specs.output.project_payload.project_payload] applies to the payload.

    Four changes, each the mirror of one the payload undergoes:

    - hidden properties are removed, and dropped from ``required``, which is
      left out when nothing in it remains;
    - a marking's ``description`` becomes the property's ``"description"``, so
      a handle says what it is for in the schema a model reads without that
      wording reaching any other reader;
    - a field with labelled choices is restated in its **displays**, because
      that is what the projected payload carries: an ``enum``'s values are
      replaced, and a ``oneOf``'s ``const``s are, each losing the ``title``
      that annotated the value it now equals. A ``"type"`` stated beside them
      is restated as the types of the values now listed, ``"null"`` last, so a
      display string is never described as the integer it replaced, and a
      display two values share is listed once, so a row served it matches one
      ``oneOf`` entry rather than two. Not on a ``HANDLE``, which keeps its
      values on both sides: a field another tool takes as input should be
      marked one.
    - a formatted field is restated as the type its
      [`ValueFormatter`][django_service_specs.types.value_formatter.ValueFormatter]
      says it produces, plus whatever that declaration adds about the shape of
      the produced value, in place of everything the property said about the
      value before, choices included. Its ``title`` and ``description`` are
      kept, and so is a ``"null"`` in its type, since a null is never
      formatted. The type is written from ``produces`` rather than taken from
      the fragment, so a renderer cannot contradict its own advertisement. Not
      on a ``HANDLE`` either.

    Generating both sides from one declaration is the point: a schema that
    advertises a field the payload no longer carries is worse than either
    behaviour on its own.

    ``handle_description`` is the wording for a ``HANDLE`` whose marking
    declares none, and defaults to **nothing**. Telling a reader what to do
    with an identifier is advice for one kind of reader, and the kernel does
    not know which kind is reading. The transport that knows its audience
    supplies the sentence.

    Takes the **item** schema; an array's ``items`` are annotated and the
    array kept. A caller wrapping items in an envelope of its own annotates the
    item and wraps it afterwards, as
    [`spec_output_schema`][django_service_specs.schema.spec_output_schema.spec_output_schema]
    does. ``None``, or a projection with nothing in it, returns ``schema``
    itself; anything else returns a new schema and never modifies ``schema``.
    """
    # One branch to coverage, so each condition is held by its own test:
    # test_no_schema_is_still_no_schema (the first) and
    # test_an_empty_projection_returns_the_schema_itself (the second).
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
        # The mirror of the chain in ``project_payload``, in the same order and
        # for the same reason: a declared formatter is the transform its author
        # asked for, so it wins over the substitution derived from a field's
        # choices. Reorder one of these two and the schema starts describing a
        # payload nobody renders.
        formatter = projection.formatter(name)
        child = projection.nested.get(name)
        if formatter is not None:
            resolved = _formatted_schema(subschema, formatter)
        else:
            resolved = (
                _annotate(subschema, child, handle_description) if child is not None else subschema
            )
            # One branch to coverage, so each condition is held by its own test:
            # test_a_handle_keeps_its_constants (the first) and
            # test_a_field_with_no_labels_is_left_alone (the second).
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
    """Restate a property as what its formatter produces.

    Every assertion the property made - ``type``, ``format``, ``enum``,
    ``oneOf``, an array's ``items`` - described the value the presenter
    returned, and that value is no longer what the payload carries. A
    date-time states ``format: date-time``, which a formatted local date-time
    is not; keeping it would be a schema that fails its own claim while
    looking correct. So the choices' displays are never spoken here either,
    and their ``"type"`` is not restated from them: there are no choices left
    to restate it from.

    ``_CARRIED`` is what survives, because it annotates the *field* rather
    than asserting anything about its value: its ``title`` and its
    ``description``. The formatter's own fragment merges over both, so a
    formatter that wants to say something else about the field still can.

    A stated type that admits ``"null"`` still admits it, after the type the
    formatter produces: ``apply`` passes a null through unformatted, so a
    nullable field still serves one. djangorestframework-services drops it.
    Only a stated type list is read: a null stated as an ``anyOf`` member, or
    as ``None`` in an ``enum``, is the spelling a schema written elsewhere may
    use, and under a formatter it is lost, as it is there. This package's own
    output schema states nullability as a type list. Each spelling read is
    held by ``test_a_nullable_field_stays_nullable`` and
    ``test_a_field_stated_only_as_null_still_admits_it``.
    """
    carried = {key: schema[key] for key in _CARRIED if key in schema}
    formatted = {**carried, **formatter.json_schema()}
    stated = schema.get("type")
    if "null" in (stated if isinstance(stated, list) else [stated]):
        formatted["type"] = [formatted["type"], "null"]
    return formatted


def _spoken_schema(schema: dict[str, Any], labels: Mapping[Any, str]) -> dict[str, Any]:
    """Restate a choice schema in the displays the payload now carries.

    Both spellings an output schema uses are handled: a bare ``enum`` where the
    displays added nothing to some values, and ``oneOf`` of ``const`` and
    ``title`` where they did. An array of choices arrives as an array wrapping
    its element's schema, so the rewrite descends one level. A union arrives
    as ``anyOf`` from a schema written elsewhere, and each member is rewritten,
    the null one passing through untouched.

    Django allows two values one display, and a display is listed once, where
    first seen: ``oneOf`` admits a value valid under exactly one entry, so a
    display listed twice would refuse every row served it. A ``oneOf`` entry
    with no ``const`` is kept wherever it stands. This, like ``_retyped``
    below, departs from djangorestframework-services, whose walk does neither.
    """
    items = schema.get("items")
    if isinstance(items, dict):
        return {**schema, "items": _spoken_schema(items, labels)}
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
        return _retyped({**schema, "oneOf": one_of}, consts)
    return schema


def _is_listed(value: Any, listed: list[Any]) -> bool:
    """Whether ``value`` is already in ``listed``, as JSON Schema compares values.

    ``True == 1`` in Python and not in JSON Schema, where a boolean is never a
    number, so dropping one as a repeat of the other would refuse every row
    served it.
    """
    # One branch to coverage, so each condition is held by its own test:
    # test_an_enum_is_restated_in_its_display_values (the first: two displays
    # that differ) and test_a_boolean_is_not_the_number_python_says_it_equals
    # (the second).
    return any(
        value == seen and isinstance(value, bool) is isinstance(seen, bool) for seen in listed
    )


def _retyped(schema: dict[str, Any], values: list[Any]) -> dict[str, Any]:
    """``schema`` with any stated ``"type"`` restated as the types of ``values``.

    A departure from djangorestframework-services, which leaves the type as
    the serializer walk stated it.

    An output schema states a choice's type beside its values, and a display
    is a string whatever the value it replaced was, so an integer choice
    spoken as ``"Low"`` would otherwise be described as an integer and the
    projected payload would fail the projected schema. A schema that states
    no type claims nothing to contradict, one listing no value has nothing to
    restate it from, and a value JSON has no scalar name for leaves the type as
    written rather than guessed at.
    """
    # One branch to coverage, so each condition is held by its own test:
    # test_an_untyped_choice_states_no_type (the first) and
    # test_a_one_of_with_no_constant_keeps_its_type (the second).
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
    if None in values:
        names.append("null")
    return {**schema, "type": names[0] if len(names) == 1 else names}


def _description(
    projection: AudienceProjection,
    name: str,
    audience: FieldAudience,
    handle_description: str | None,
) -> str | None:
    marking = projection.fields.get(name)
    # One branch to coverage, so each condition is held by its own test:
    # test_the_handle_wording_is_for_handles_only (the first: an unmarked field)
    # and test_an_unlabelled_handle_takes_the_wording_supplied (the second).
    if marking is not None and marking.description:
        return marking.description
    return handle_description if audience is FieldAudience.HANDLE else None
