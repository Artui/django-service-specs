"""Dialect rules the schema emitters share: how null is admitted, which values may be stated, and how a declaration's extra keys join its node."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ImproperlyConfigured


def allow_null(schema: dict[str, Any]) -> dict[str, Any]:
    """``schema`` with ``"null"`` added to its type: ``{"type": "t"}`` becomes ``[t, "null"]``.

    A type list rather than an ``anyOf`` of two schemas, because the node is one
    shape that may also be absent, and a list keeps every other keyword beside
    the type it describes. A reader choosing a widget, or a model choosing a
    value, reads ``type`` first; an ``anyOf`` makes both go looking for it.

    Returns a new mapping and never modifies ``schema``. A node with no
    ``type`` is copied as it is, since it admits null already: a file's, which
    no JSON type describes, and an array's undeclared element (``{}``).
    """
    if "type" not in schema:
        return dict(schema)
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


def with_schema_extra(
    schema: dict[str, Any], extra: dict[str, Any] | None, *, where: str
) -> dict[str, Any]:
    """``schema`` with a declaration's ``json_schema_extra`` added, refusing a key it already states.

    The last step of a ``Parameter``'s node and an ``OutputField``'s, so the
    keys compared are every one the declaration produced: its type, its
    nullability, its choices, its bounds, its default and its prose. Neither
    side wins a key both state. The extra overriding the declaration would
    advertise a contract the shape check does not hold, a ``type`` or an
    ``enum`` it never enforces; the declaration overriding the extra would
    drop what an author wrote. So the declaration is refused when the schema
    is built, naming the keys, and an adapter filling the extra leaves out
    what it filled a field with. Only the node's top level is compared, so a
    flat array's element is the declaration's alone: its ``items`` is a key
    the node states.

    A new mapping, as every node is; the extra's values are placed in it as
    declared, not copied, as a default's are.
    """
    if extra is None:
        return schema
    repeated = sorted(schema.keys() & extra.keys())
    if repeated:
        raise ImproperlyConfigured(
            f"{where}: json_schema_extra repeats {repeated}, which the declaration already "
            "states. Declare each in one place: remove it from json_schema_extra, or from the "
            "field that states it."
        )
    return {**schema, **extra}
