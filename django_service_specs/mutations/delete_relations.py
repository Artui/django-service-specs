from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.mutations.change_result import ChangeResult, ModelT
from django_service_specs.mutations.nested_writes import cascade_owned
from django_service_specs.mutations.utils import relation_map
from django_service_specs.relations.relation_spec import RelationSpec


def delete_relations(
    instance: ModelT,
    *,
    relations: Mapping[str, RelationSpec],
    context: Mapping[str, Any] | None = None,
) -> ChangeResult[ModelT]:
    """Remove the rows ``instance`` owns, deepest first, and leave ``instance``."""
    collections, singular = cascade_owned(instance, relation_map(relations), context=context)
    return ChangeResult(
        instance=instance, created=False, changes=(), children=collections, relations=singular
    )
