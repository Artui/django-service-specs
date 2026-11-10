from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.mutations.change_result import ChangeResult, ModelT
from django_service_specs.mutations.nested_writes import acascade_owned
from django_service_specs.mutations.utils import relation_map
from django_service_specs.relations.relation_spec import RelationSpec


async def adelete_relations(
    instance: ModelT,
    *,
    relations: Mapping[str, RelationSpec],
    context: Mapping[str, Any] | None = None,
) -> ChangeResult[ModelT]:
    """Async variant of ``delete_relations``."""
    collections, singular = await acascade_owned(instance, relation_map(relations), context=context)
    return ChangeResult(
        instance=instance, created=False, changes=(), children=collections, relations=singular
    )
