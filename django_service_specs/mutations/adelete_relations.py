"""Async variant of ``delete_relations``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.mutations.change_result import ChangeResult, ModelT
from django_service_specs.mutations.utils import acascade_owned, relation_map
from django_service_specs.relations.relation_spec import RelationSpec


async def adelete_relations(
    instance: ModelT,
    *,
    relations: Mapping[str, RelationSpec],
    context: Mapping[str, Any] | None = None,
) -> ChangeResult[ModelT]:
    """Async variant of [`delete_relations`][django_service_specs.mutations.delete_relations.delete_relations].

    The same rule, the same order and the same report, through Django's async
    ORM. A row service a spec declares must be ``async def`` here, as in every
    async helper: one the loop cannot await is refused, naming its slot.
    """
    collections, singular = await acascade_owned(instance, relation_map(relations), context=context)
    return ChangeResult(
        instance=instance, created=False, changes=(), children=collections, relations=singular
    )
