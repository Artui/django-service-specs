from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from django_service_specs.mutations.change_result import ModelT
from django_service_specs.mutations.create_from_input import create_from_input
from django_service_specs.mutations.utils import handed_on, resolve_m2m
from django_service_specs.relations.relation_spec import RelationSpec


def create_model(
    model: type[ModelT],
    *,
    field_map: dict[str, str] | None = None,
    exclude_fields: list[str] | None = None,
    m2m: Mapping[str, Any] | Callable[[Any], Mapping[str, Any]] | None = None,
    relations: Mapping[str, RelationSpec] | None = None,
) -> Callable[..., ModelT]:
    """A service that builds a row of ``model`` from its validated ``data``, and returns the row."""

    def _service(*, data: Any, call_context: dict[str, Any] | None = None, **kwargs: Any) -> ModelT:
        return create_from_input(
            model,
            data,
            field_map=field_map,
            exclude_fields=exclude_fields,
            m2m=resolve_m2m(m2m, data),
            relations=relations,
            context=handed_on(kwargs, call_context),
        ).instance

    return _service
