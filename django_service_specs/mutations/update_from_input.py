from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.mutations.change_result import ChangeResult, ModelT
from django_service_specs.mutations.nested_writes import update_instance
from django_service_specs.relations.relation_spec import RelationSpec


def update_from_input(
    instance: ModelT,
    data: Any,
    *,
    field_map: dict[str, str] | None = None,
    exclude_fields: list[str] | None = None,
    m2m: dict[str, Any] | None = None,
    update_fields: bool | list[str] = True,
    relations: Mapping[str, RelationSpec] | None = None,
    context: Mapping[str, Any] | None = None,
) -> ChangeResult[ModelT]:
    """Update ``instance`` with values from ``data``, persisting only deltas."""
    return update_instance(
        instance,
        data,
        field_map=field_map,
        exclude_fields=exclude_fields,
        m2m=m2m,
        update_fields=update_fields,
        relations=relations,
        context=context,
    )
