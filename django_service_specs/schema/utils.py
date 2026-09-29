"""Dialect rules the schema emitters share: how null is admitted, and which values may be stated."""

from __future__ import annotations

from typing import Any


def allow_null(schema: dict[str, Any]) -> dict[str, Any]:
    """``schema`` with ``"null"`` added to its type: ``{"type": "t"}`` becomes ``[t, "null"]``.

    A type list rather than an ``anyOf`` of two schemas, because the node is one
    shape that may also be absent, and a list keeps every other keyword beside
    the type it describes. A reader choosing a widget, or a model choosing a
    value, reads ``type`` first; an ``anyOf`` makes both go looking for it.

    Returns a new mapping and never modifies ``schema``. Only a typed node is
    passed here: every Parameter and OutputField declares its type, and an
    array's untyped element (``{}``) already admits null.
    """
    return {**schema, "type": [schema["type"], "null"]}


def is_json_native(value: Any) -> bool:
    """Whether ``value`` survives the JSON encoding every transport performs on a schema.

    A schema carries a value in two places, a ``default`` and a choice, and both
    reach the wire as they are. A ``Decimal``, a date or a model row there does
    not describe the input less well - it breaks the encoding, so the transport
    fails to list the operation at all. The emitters leave such a value out
    rather than restate it in a form the declaration did not choose.

    ``bool`` needs no case of its own: it is an ``int``, and both are native.
    """
    if value is None or isinstance(value, (str, int, float)):
        return True
    if isinstance(value, (list, tuple)):
        return all(is_json_native(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and is_json_native(item) for key, item in value.items())
    return False
