from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from django_service_specs.mutations.change_result import ModelT
from django_service_specs.mutations.update_from_input import update_from_input
from django_service_specs.mutations.utils import handed_on, resolve_m2m
from django_service_specs.relations.relation_spec import RelationSpec


def update_model(
    model: type[ModelT],
    *,
    field_map: dict[str, str] | None = None,
    exclude_fields: list[str] | None = None,
    m2m: Mapping[str, Any] | Callable[[Any], Mapping[str, Any]] | None = None,
    update_fields: bool | list[str] = True,
    relations: Mapping[str, RelationSpec] | None = None,
) -> Callable[..., ModelT]:
    """A service that writes the validated ``data`` onto the resolved row, and returns the row."""

    def _service(
        *, instance: ModelT, data: Any, call_context: dict[str, Any] | None = None, **kwargs: Any
    ) -> ModelT:
        return update_from_input(
            instance,
            data,
            field_map=field_map,
            exclude_fields=exclude_fields,
            m2m=resolve_m2m(m2m, data),
            update_fields=update_fields,
            relations=relations,
            context=handed_on(kwargs, call_context),
        ).instance

    return _service
