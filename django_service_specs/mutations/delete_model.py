from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from django_service_specs.mutations.change_result import ModelT
from django_service_specs.mutations.delete_relations import delete_relations
from django_service_specs.mutations.utils import handed_on, relation_map
from django_service_specs.relations.relation_spec import RelationSpec


def delete_model(
    model: type[ModelT],
    *,
    soft_delete: Callable[[ModelT], None] | None = None,
    relations: Mapping[str, RelationSpec] | None = None,
) -> Callable[..., None]:
    """A service that deletes the resolved row, after the rows it owns, and returns ``None``."""
    declared = relation_map(relations)

    def _service(
        *, instance: ModelT, call_context: dict[str, Any] | None = None, **kwargs: Any
    ) -> None:
        if declared:
            delete_relations(instance, relations=declared, context=handed_on(kwargs, call_context))
        if soft_delete is not None:
            soft_delete(instance)
        else:
            instance.delete()

    return _service
