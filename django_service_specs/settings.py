from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

_MAX_ARRAY_LENGTH = "SERVICE_SPECS_MAX_ARRAY_LENGTH"
# Django's own ``DATA_UPLOAD_MAX_NUMBER_FIELDS``: the line a form body already
# stops at, which a comma-separated query value and a JSON list both pass by.
_DEFAULT_MAX_ARRAY_LENGTH = 1000


def max_array_length() -> int | None:
    """``SERVICE_SPECS_MAX_ARRAY_LENGTH``: the most elements an array takes by default."""
    value: Any = getattr(settings, _MAX_ARRAY_LENGTH, _DEFAULT_MAX_ARRAY_LENGTH)
    if value is not None and not (type(value) is int and value >= 0):
        raise ImproperlyConfigured(
            f"{_MAX_ARRAY_LENGTH} must be a non-negative int or None; got {value!r}. It is the "
            "most elements an array takes where its parameter declares no max_length."
        )
    return value
