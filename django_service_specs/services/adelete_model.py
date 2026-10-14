from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from django_service_specs.mutations.adelete_relations import adelete_relations
from django_service_specs.mutations.change_result import ModelT
from django_service_specs.mutations.utils import relation_map
from django_service_specs.relations.relation_spec import RelationSpec


def adelete_model(
    model: type[ModelT],
    *,
    soft_delete: Callable[[ModelT], Awaitable[None]] | None = None,
    relations: Mapping[str, RelationSpec] | None = None,
) -> Callable[..., Awaitable[None]]:
    """The async twin of [`delete_model`][django_service_specs.services.delete_model.delete_model].

    Deletes with ``await instance.adelete()``, after the cascade
    [`adelete_relations`][django_service_specs.mutations.adelete_relations.adelete_relations]
    runs by the rule ``delete_model`` states. ``soft_delete`` is an
    ``async def`` called with the row in place of ``adelete()``.
    """
    declared = relation_map(relations)

    async def _service(*, instance: ModelT, **kwargs: Any) -> None:
        if declared:
            await adelete_relations(instance, relations=declared, context=kwargs)
        if soft_delete is not None:
            await soft_delete(instance)
        else:
            await instance.adelete()

    return _service
