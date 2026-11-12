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
    """A service that deletes the resolved row, after the rows it owns, and returns ``None``.

    The service a delete operation would otherwise write by hand:

        def delete_author(*, instance: Author, **_: Any) -> None:
            instance.delete()

    ``model`` is not read, as in
    [`update_model`][django_service_specs.mutations.update_model.update_model]:
    the row is the ``instance`` the spec's instance selector resolved.

    ``soft_delete`` is called with the row *instead of* ``instance.delete()``,
    for a row that is retired rather than removed:

        def archive(instance: Author) -> None:
            instance.is_archived = True
            instance.save(update_fields=["is_archived"])

        delete_model(Author, soft_delete=archive)

    So no row is deleted and Django sends no ``pre_delete`` or ``post_delete``
    for it.

    ``relations`` is the map the writes take, and what it declares goes
    **before** the row, deepest first, through
    [`delete_relations`][django_service_specs.mutations.delete_relations.delete_relations]:
    the rows the instance owns are disposed of, a many-to-many loses its
    membership, and a forward relation is left alone. It is the cascade a
    database will not run - a ``PROTECT`` foreign key, or a soft delete, which
    removes no row for Django to cascade from - and the one a declared
    ``delete_service`` sees row by row. A value that is not a relation spec is
    refused with ``ImproperlyConfigured`` here, when the service is built,
    rather than at its first call. With no map, or an empty one, nothing but
    the row is touched.

    The service opens no transaction: dispatch runs it inside one, so a refused
    cascade leaves every row in place. It absorbs the rest of the pool and
    hands it on, with the call's context it names, as the cascade's
    ``context``, so a row's ``delete_service`` can see who is calling and,
    by naming ``call_context``, the very dict the call's other stages share.
    """
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
