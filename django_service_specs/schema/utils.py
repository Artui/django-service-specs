"""Dialect rules the schema emitters share: how null is admitted, and how a declaration's extra keys join its node."""

from __future__ import annotations

from typing import Any


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


def with_schema_extra(schema: dict[str, Any], extra: dict[str, Any] | None) -> dict[str, Any]:
    """``schema`` with a declaration's ``json_schema_extra`` added.

    The last step of a ``Parameter``'s node and an ``OutputField``'s. No key is
    compared here: the declaration refused, where it was written, every keyword
    its fields can make the builder state, so the two never share one. That
    refusal is made once rather than per build because a key the builder
    states on one build and not another - ``maxItems`` under the array cap,
    ``additionalProperties`` under ``REJECT``, a default left out for being no
    JSON value - would otherwise make one declaration valid on one route and
    refused on the next. test_the_keywords_refused_are_the_ones_the_builder_states
    holds that the builders state nothing else.

    A new mapping, as every node is; the extra's values are placed in it as
    the declaration holds them, as a default's are.
    """
    if extra is None:
        return schema
    return {**schema, **extra}
