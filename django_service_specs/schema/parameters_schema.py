"""``parameters_schema`` - the JSON Schema of what an operation takes."""

from __future__ import annotations

from typing import Any

from django_service_specs.parameters.max_length_in_force import max_length_in_force
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.parameters.utils import unknown_arguments_policy
from django_service_specs.schema.utils import allow_null, is_json_native, with_schema_extra
from django_service_specs.types.unknown_arguments import UnknownArguments
from django_service_specs.types.unset import UNSET


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
      that declares no ``items`` and accepts any element. The array's
      ``format`` and bounds describe each element, so they go on ``items``,
      as its choices do: a CSV number filter's are ``{"type": "string",
      "format": "decimal", "minimum": -1e+50, "maximum": 1e+50}``.
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
    - **Bounds** are ``"minimum"`` and ``"maximum"``, inclusive, as declared.
      JSON Schema applies them to a number instance only, so on a decimal
      string a validating client enforces neither; the shape check does, and
      they tell a reader where the line is.
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
      depth: what the declaration cannot spell, such as a ``pattern`` or a
      string's ``maxLength``, stated for the Validator that enforces it. A key
      the declaration already states on that node is refused with
      ``ImproperlyConfigured`` rather than overridden either way, so the
      schema never claims a type, a choice or a bound the shape check does
      not hold.

    Nothing else, deliberately. No ``title`` on a property, because a Parameter
    has no label of its own; a ``title`` is only ever a choice's.
    No ``$defs`` or ``$ref`` ever: most MCP clients refuse a schema with a
    reference in it, so every schema is flat and self-contained, however deep
    the declaration nests. No ``$schema`` key, which a transport adds if its
    wire wants one. And no bound the shape check does not enforce
    (``maxLength``, a Validator's ``max_value``) unless a ``json_schema_extra``
    states it: the Validator enforces those.
    The one stated without being declared is an array's default maximum,
    because the shape check enforces it.

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
        schema = {"type": "array", "items": _items_schema(param, policy), **_lengths(param)}
    elif param.fields is not None:
        # Only an object carries ``fields``; ``Parameter`` refuses them elsewhere.
        schema = _object_schema(param.fields, policy)
    elif param.type in ("file", "any"):
        # One branch to coverage, so each type is held by its own test:
        # test_a_file_states_no_type and test_any_states_no_type.
        schema = {}
    else:
        schema = {"type": param.type}
    # An array's format, bounds and choices describe its elements, and
    # ``_items_schema`` states them. Held by
    # test_an_array_states_its_element_s_format_and_bounds_on_items_and_not_on_itself
    # and test_an_arrays_choices_constrain_each_item_and_not_the_array, which
    # fail without it, for the array node would carry them as well.
    if param.type != "array":
        schema.update(_reading(param))
        # Held by test_a_scalar_states_its_type, a parameter with no choices.
        if param.choices is not None:
            schema.update(_choices(param, nullable=param.nullable))
    if param.nullable:
        schema = allow_null(schema)
    # ``UNSET``, the declaration of no default, is not a JSON value either, so
    # this one test leaves out both a missing default and one JSON cannot carry.
    # A second ``is not UNSET`` conjunct would change nothing a test could see.
    # Held by test_a_default_json_cannot_carry_is_left_out, whose [undeclared]
    # case is the missing default.
    if is_json_native(param.default):
        schema["default"] = param.default
    if param.help:
        # ``str()`` because an adapter may pass a lazy translation through, which
        # is not a JSON value: it is rendered in the language active now.
        schema["description"] = str(param.help)
    # Last, so every key the declaration states is there to be compared.
    return with_schema_extra(schema, param.json_schema_extra, where=f"Parameter {param.name!r}")


def _reading(param: Parameter) -> dict[str, Any]:
    """The value's ``format`` and bounds: a scalar's own, or an array's element's.

    Bounds are stated on a decimal string too, where a validating client
    passes them by: JSON Schema reads ``minimum`` and ``maximum`` on a number
    instance only. The shape check is what enforces them there, and a reader
    still learns the bound. Three arcs, each held by
    test_a_bound_is_stated_beside_the_type.
    """
    reading: dict[str, Any] = {}
    if param.format is not None:
        reading["format"] = param.format
    if param.minimum is not None:
        reading["minimum"] = param.minimum
    if param.maximum is not None:
        reading["maximum"] = param.maximum
    return reading


def _lengths(param: Parameter) -> dict[str, Any]:
    """An array's ``minItems`` as declared, and its ``maxItems`` as in force: declared or the default."""
    lengths: dict[str, Any] = {}
    # Two arcs, held by test_declared_lengths_are_stated_as_min_and_max_items
    # and test_a_setting_of_none_states_no_maximum.
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
        # One branch to coverage, so each condition is held by its own test:
        # test_an_array_with_no_items_accepts_any_element and
        # test_an_array_of_files_has_untyped_items.
        schema = {}
    else:
        # ``Parameter`` takes a format or a bound on an array only for a
        # typed element that can carry it, so a row, a file and an undeclared
        # element carry neither and need no reading.
        schema = {"type": items, **_reading(param)}
    if param.choices is not None:
        # Widened with null by the element's nullability and never the array's:
        # the shape check keeps a null element only where ``items_nullable``
        # says so, and does so before it reads the choices. An untyped element
        # admits null only when the choices list it.
        schema.update(_choices(param, nullable=param.items_nullable))
    if param.items_nullable:
        # ``Parameter`` refuses ``items_nullable`` without ``items``, so the
        # element is declared: typed, or a file, which ``allow_null`` leaves be.
        schema = allow_null(schema)
    return schema


def _choices(param: Parameter, *, nullable: bool) -> dict[str, Any]:
    """``{"enum": ...}`` or ``{"anyOf": ...}`` for the accepted values, or ``{}`` when one cannot be stated."""
    choices = param.choices or ()
    if not all(is_json_native(value) for value in choices):
        return {}
    labels = param.choice_labels or ()
    # One branch to coverage, so each condition is held by its own test:
    # test_choices_are_an_enum_beside_the_type (no labels at all) and
    # test_labels_that_only_repeat_their_values_stay_an_enum (labels that add
    # nothing).
    if not any(str(label) != str(value) for value, label in labels):
        values = list(choices)
        # The shape check lets ``None`` through a nullable parameter before it
        # reads the choices, so an enum that did not list it would refuse a call
        # that runs.
        if nullable and None not in values:
            values.append(None)
        return {"enum": values}
    listed: list[Any] = []
    entries: list[dict[str, Any]] = []
    for value in choices:
        # Each value once, so the entries stay disjoint: held by
        # test_a_choice_declared_twice_is_one_entry.
        if any(_same(value, seen) for seen in listed):
            continue
        listed.append(value)
        entry: dict[str, Any] = {"type": "null"} if value is None else {"const": value}
        label = next((label for known, label in labels if _same(known, value)), None)
        if label is not None:
            entry["title"] = str(label)
        entries.append(entry)
    # The ``None`` the enum gains, as the enum gains it. One branch to coverage,
    # so each condition is held by its own test:
    # test_labelled_choices_are_any_of_pairs_of_const_and_title (nullability) and
    # test_a_labelled_null_is_listed_once (the null already listed).
    if nullable and None not in choices:
        entries.append({"type": "null"})
    return {"anyOf": entries}


def _same(one: Any, other: Any) -> bool:
    """Whether two choices are one JSON value: Python's equality, with ``True`` apart from ``1``.

    So a choice declared twice is one ``anyOf`` entry, and ``True`` and ``1``
    are two.

    The second condition is held by test_a_choice_declared_twice_is_one_entry.
    """
    return one == other and isinstance(one, bool) == isinstance(other, bool)
