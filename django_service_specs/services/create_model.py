from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from django_service_specs.mutations.change_result import ModelT
from django_service_specs.mutations.create_from_input import create_from_input
from django_service_specs.mutations.utils import resolve_m2m
from django_service_specs.relations.relation_spec import RelationSpec


def create_model(
    model: type[ModelT],
    *,
    field_map: dict[str, str] | None = None,
    exclude_fields: list[str] | None = None,
    m2m: Mapping[str, Any] | Callable[[Any], Mapping[str, Any]] | None = None,
    relations: Mapping[str, RelationSpec] | None = None,
) -> Callable[..., ModelT]:
    """A service that builds a row of ``model`` from its validated ``data``, and returns the row.

    The service a create operation would otherwise write by hand:

        def create_author(*, data: AuthorIn, **_: Any) -> Author:
            return create_from_input(Author, data).instance

    ``field_map``, ``exclude_fields`` and ``relations`` are handed to
    [`create_from_input`][django_service_specs.mutations.create_from_input.create_from_input]
    as they are, so one ``relations`` map writes every nested kind, a reverse
    foreign key's
    [`ChildSpec`][django_service_specs.relations.child_spec.ChildSpec] among
    them. ``m2m`` is a static mapping, or a callable handed the validated
    ``data`` that returns one, which is the usual case when the rows to link
    arrive in the arguments:

        create_model(Post, m2m=lambda data: {"tags": data.tags})

    The service returns the row, not the
    [`ChangeResult`][django_service_specs.mutations.change_result.ChangeResult],
    since the row is what a create's output presents. It opens no transaction:
    dispatch runs a service inside one, which covers the row and every nested
    write. It takes ``**kwargs``, so the rest of the pool - the ``user`` and
    any registered seed - is absorbed rather than refused, and the same pool
    is handed on as the helper's ``context``, so a row service a relation spec
    declares can see who is calling.
    """

    def _service(*, data: Any, **kwargs: Any) -> ModelT:
        return create_from_input(
            model,
            data,
            field_map=field_map,
            exclude_fields=exclude_fields,
            m2m=resolve_m2m(m2m, data),
            relations=relations,
            context=kwargs,
        ).instance

    return _service
