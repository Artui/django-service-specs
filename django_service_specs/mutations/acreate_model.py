from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from django_service_specs.mutations.acreate_from_input import acreate_from_input
from django_service_specs.mutations.change_result import ModelT
from django_service_specs.mutations.utils import resolve_m2m
from django_service_specs.relations.relation_spec import RelationSpec


def acreate_model(
    model: type[ModelT],
    *,
    field_map: dict[str, str] | None = None,
    exclude_fields: list[str] | None = None,
    m2m: Mapping[str, Any] | Callable[[Any], Mapping[str, Any]] | None = None,
    relations: Mapping[str, RelationSpec] | None = None,
) -> Callable[..., Awaitable[ModelT]]:
    """The async twin of [`create_model`][django_service_specs.mutations.create_model.create_model].

    An ``async def`` service over
    [`acreate_from_input`][django_service_specs.mutations.acreate_from_input.acreate_from_input],
    so [`adispatch`][django_service_specs.dispatch.adispatch.adispatch] awaits it
    rather than bridging it. Every row service its ``relations`` declare is an
    ``async def`` too, which the async helpers check.
    """

    async def _service(*, data: Any, **kwargs: Any) -> ModelT:
        result = await acreate_from_input(
            model,
            data,
            field_map=field_map,
            exclude_fields=exclude_fields,
            m2m=resolve_m2m(m2m, data),
            relations=relations,
            context=kwargs,
        )
        return result.instance

    return _service
