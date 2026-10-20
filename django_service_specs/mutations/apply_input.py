"""In-memory attribute application — no save, no DB access."""

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
    """Set attributes from ``data`` onto ``instance`` without saving.

    Returns a [`ChangeResult`][django_service_specs.mutations.change_result.ChangeResult]
    describing fields whose value actually changed. Useful when a service wants to
    inspect what the input would change before deciding whether to persist.

    A file field is set as ``update_from_input`` writes it: ``None`` keeps the
    file, and ``False`` leaves none."""
    new_values = filter_input(
        coerce_to_dict(data), field_map=field_map, exclude_fields=exclude_fields
    )
    changes = assign_changed_values(instance, new_values)
    return ChangeResult(instance=instance, created=False, changes=changes)
