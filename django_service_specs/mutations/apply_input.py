from __future__ import annotations

from typing import Any

from django.db.models import Model

from django_service_specs.mutations.change_result import ChangeResult
from django_service_specs.mutations.utils import assign_changed_values, coerce_to_dict, filter_input


def apply_input(
    instance: Model,
    data: Any,
    *,
    field_map: dict[str, str] | None = None,
    exclude_fields: list[str] | None = None,
) -> ChangeResult:
    """Set attributes from ``data`` onto ``instance`` without saving."""
    new_values = filter_input(
        coerce_to_dict(data), field_map=field_map, exclude_fields=exclude_fields
    )
    changes = assign_changed_values(instance, new_values)
    return ChangeResult(instance=instance, created=False, changes=changes)
