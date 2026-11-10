from __future__ import annotations

from typing import Any


def allow_null(schema: dict[str, Any]) -> dict[str, Any]:
    """``schema`` with ``"null"`` added to its type: ``{"type": "t"}`` becomes ``[t, "null"]``."""
    if "type" not in schema:
        return dict(schema)
    return {**schema, "type": [schema["type"], "null"]}


def with_schema_extra(schema: dict[str, Any], extra: dict[str, Any] | None) -> dict[str, Any]:
    """``schema`` with a declaration's ``json_schema_extra`` added."""
    if extra is None:
        return schema
    return {**schema, **extra}
