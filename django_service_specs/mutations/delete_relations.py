"""Remove what a row owns through its declared relations, before the row goes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.mutations.change_result import ChangeResult, ModelT
from django_service_specs.mutations.utils import cascade_owned, relation_map
from django_service_specs.relations.relation_spec import RelationSpec


def delete_relations(
    instance: ModelT,
    *,
    relations: Mapping[str, RelationSpec],
    context: Mapping[str, Any] | None = None,
) -> ChangeResult[ModelT]:
    """Remove the rows ``instance`` owns, deepest first, and leave ``instance``.

    The cascade for a delete service to run where the database will not: a
    ``PROTECT`` foreign key, a relation whose row services must see each
    removal, or a soft delete, which Django never cascades through because no
    row is deleted. The service deletes (or retires) ``instance`` itself
    afterwards, inside the same atomic block.

    ``relations`` is the same map the write helpers take, so one declaration
    describes both how a payload is written and what goes when the row does.
    **One rule covers every kind: the rows the instance owns are disposed of,
    and the rows it merely points at are not.**

    - A [`ChildSpec`][django_service_specs.relations.child_spec.ChildSpec] or
      [`GenericRelationSpec`][django_service_specs.relations.generic_relation_spec.GenericRelationSpec]
      collection, and a
      [`ReverseOneToOneSpec`][django_service_specs.relations.reverse_one_to_one_spec.ReverseOneToOneSpec]
      row, is disposed of after its own declared relations, so a non-nullable
      grandchild goes first. Each row is deleted, unlinked or handed to the
      spec's ``delete_service`` by the rule a write removing it follows: the
      spec's ``orphan`` setting, or the service when one is declared.
    - A [`ManyToManySpec`][django_service_specs.relations.many_to_many_spec.ManyToManySpec]
      loses its membership, and its target rows survive.
    - A [`ForwardRelationSpec`][django_service_specs.relations.forward_relation_spec.ForwardRelationSpec]
      is reported untouched rather than refused: its row is not the
      instance's, and refusing it would make a map that is right for writing
      impossible to cascade.

    The returned [`ChangeResult`][django_service_specs.mutations.change_result.ChangeResult]
    reports the collections under ``children`` and the one-row kinds under
    ``relations``, as a write does, with no field changes. The instance's
    cached relations are brought in line with the removal, so an instance
    that outlives its cascade renders without the rows it lost.

    ``context`` is an **opaque** mapping forwarded verbatim into the pool of
    every row service the specs declare; this helper never reads it.
    """
    collections, singular = cascade_owned(instance, relation_map(relations), context=context)
    return ChangeResult(
        instance=instance, created=False, changes=(), children=collections, relations=singular
    )
