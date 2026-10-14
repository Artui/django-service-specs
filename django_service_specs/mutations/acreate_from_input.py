"""Async equivalent of
[`create_from_input`][django_service_specs.mutations.create_from_input.create_from_input]."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.mutations.change_result import ChangeResult, ModelT
from django_service_specs.mutations.nested_writes import acreate_instance
from django_service_specs.relations.relation_spec import RelationSpec


async def acreate_from_input(
    model: type[ModelT],
    data: Any,
    *,
    field_map: dict[str, str] | None = None,
    exclude_fields: list[str] | None = None,
    m2m: dict[str, Any] | None = None,
    relations: Mapping[str, RelationSpec] | None = None,
    context: Mapping[str, Any] | None = None,
) -> ChangeResult[ModelT]:
    """Async sibling of
    [`create_from_input`][django_service_specs.mutations.create_from_input.create_from_input]
    using ``asave()``/``aset()``."""
    return await acreate_instance(
        model,
        data,
        field_map=field_map,
        exclude_fields=exclude_fields,
        m2m=m2m,
        relations=relations,
        context=context,
    )
