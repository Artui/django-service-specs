from __future__ import annotations

from typing import Any

from django_service_specs.selectors.is_queryset import is_queryset


def materialize_retrieve(result: Any) -> Any:
    """Collapse a RETRIEVE selector's return to the single instance, or ``None``."""
    return result.first() if is_queryset(result) else result
