from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from django_service_specs.types.json_schema_registry import JsonSchemaRegistry

_MAX_ARRAY_LENGTH = "SERVICE_SPECS_MAX_ARRAY_LENGTH"
# Django's own ``DATA_UPLOAD_MAX_NUMBER_FIELDS``: the line a form body already
# stops at, which a comma-separated query value and a JSON list both pass by.
_DEFAULT_MAX_ARRAY_LENGTH = 1000
_FIELD_SCHEMA_REGISTRY = "SERVICE_SPECS_FIELD_SCHEMA_REGISTRY"


def max_array_length() -> int | None:
    """``SERVICE_SPECS_MAX_ARRAY_LENGTH``: the most elements an array takes by default."""
    value: Any = getattr(settings, _MAX_ARRAY_LENGTH, _DEFAULT_MAX_ARRAY_LENGTH)
    if value is not None and not (type(value) is int and value >= 0):
        raise ImproperlyConfigured(
            f"{_MAX_ARRAY_LENGTH} must be a non-negative int or None; got {value!r}. It is the "
            "most elements an array takes where its parameter declares no max_length."
        )
    return value


def field_schema_registry() -> JsonSchemaRegistry | None:
    """``SERVICE_SPECS_FIELD_SCHEMA_REGISTRY``: the project's field schema rules, or ``None``."""
    path: Any = getattr(settings, _FIELD_SCHEMA_REGISTRY, None)
    if path is None:
        return None
    if not isinstance(path, str):
        raise ImproperlyConfigured(
            f"{_FIELD_SCHEMA_REGISTRY} must be the dotted path to a JsonSchemaRegistry; got "
            f"{path!r}."
        )
    try:
        registry = import_string(path)
    except ImportError as error:
        raise ImproperlyConfigured(
            f"{_FIELD_SCHEMA_REGISTRY} names {path!r}, which cannot be imported: {error}"
        ) from error
    if not isinstance(registry, JsonSchemaRegistry):
        raise ImproperlyConfigured(
            f"{_FIELD_SCHEMA_REGISTRY} names {path!r}, a {type(registry).__name__}, not a "
            "JsonSchemaRegistry."
        )
    return registry
