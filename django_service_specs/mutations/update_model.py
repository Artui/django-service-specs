from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from django_service_specs.mutations.change_result import ModelT
from django_service_specs.mutations.update_from_input import update_from_input
from django_service_specs.mutations.utils import resolve_m2m
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
    """A service that writes the validated ``data`` onto the resolved row, and returns the row.

    The service an update operation would otherwise write by hand:

        def update_author(*, instance: Author, data: AuthorIn, **_: Any) -> Author:
            return update_from_input(instance, data).instance

    ``model`` is not read: it is taken for symmetry with
    [`create_model`][django_service_specs.mutations.create_model.create_model] and
    to bind the row's type for a type checker, since the row is the
    ``instance`` the spec's instance selector resolved. ``field_map``,
    ``exclude_fields``, ``update_fields`` and ``relations`` are handed to
    [`update_from_input`][django_service_specs.mutations.update_from_input.update_from_input]
    as they are, and ``m2m`` is read as ``create_model`` reads it.

    The service returns the row rather than the
    [`ChangeResult`][django_service_specs.mutations.change_result.ChangeResult],
    opens no transaction of its own, absorbs the rest of the pool and hands it
    on as ``context``, as ``create_model``'s does.
    """

    def _service(*, instance: ModelT, data: Any, **kwargs: Any) -> ModelT:
        return update_from_input(
            instance,
            data,
            field_map=field_map,
            exclude_fields=exclude_fields,
            m2m=resolve_m2m(m2m, data),
            update_fields=update_fields,
            relations=relations,
            context=kwargs,
        ).instance

    return _service
