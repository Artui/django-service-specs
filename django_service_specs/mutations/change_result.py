"""The structured result returned by every mutation helper."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from django.db.models import Model

from django_service_specs.mutations.child_collection_change import ChildCollectionChange
from django_service_specs.mutations.field_change import FieldChange
from django_service_specs.mutations.related_object_change import RelatedObjectChange

ModelT = TypeVar("ModelT", bound=Model)


@dataclass(frozen=True)
class ChangeResult(Generic[ModelT]):
    """Outcome of a mutation helper call.

    ``instance`` is the model instance after the mutation. ``created`` is True iff this
    came from
    [`create_from_input`][django_service_specs.mutations.create_from_input.create_from_input]
    /
    [`acreate_from_input`][django_service_specs.mutations.acreate_from_input.acreate_from_input].
    ``changes`` records every field whose value actually differed from its prior value
    (or from ``UNSET`` for creates).

    Every relation declared in ``relations=`` reports in one of two fields, chosen by
    the relation's shape. ``children`` carries one
    [`ChildCollectionChange`][django_service_specs.mutations.child_collection_change.ChildCollectionChange]
    per **collection**: a reverse-FK
    [`ChildSpec`][django_service_specs.relations.child_spec.ChildSpec], a
    [`GenericRelationSpec`][django_service_specs.relations.generic_relation_spec.GenericRelationSpec]
    and a
    [`ManyToManySpec`][django_service_specs.relations.many_to_many_spec.ManyToManySpec].
    ``relations`` carries one
    [`RelatedObjectChange`][django_service_specs.mutations.related_object_change.RelatedObjectChange]
    per **one-row** relation: a
    [`ForwardRelationSpec`][django_service_specs.relations.forward_relation_spec.ForwardRelationSpec]
    and a
    [`ReverseOneToOneSpec`][django_service_specs.relations.reverse_one_to_one_spec.ReverseOneToOneSpec].
    A collection reports tuples of pks and a one-row relation reports an outcome, so
    they are different carriers. Both are empty when no relation is declared, and a
    declared relation the input omits still gets its entry, reporting nothing.
    A forward relation shows up **twice** and means two different things — here as
    what happened to the row it points at, and in ``changes`` as the parent's
    foreign-key column, which only appears if it actually changed.

    The class is generic over the concrete model type: callers that pass
    ``Author`` into a mutation helper get back a ``ChangeResult[Author]``
    whose ``.instance`` is typed as ``Author``. The bare name
    ``ChangeResult`` (no parameter) resolves to ``ChangeResult[Model]`` and
    keeps working for callers that don't care.
    """

    instance: ModelT
    created: bool
    changes: tuple[FieldChange, ...]
    children: tuple[ChildCollectionChange, ...] = field(default_factory=tuple)
    relations: tuple[RelatedObjectChange, ...] = field(default_factory=tuple)

    @property
    def changed_fields(self) -> tuple[str, ...]:
        """Names of every field present in ``changes``."""
        return tuple(change.field for change in self.changes)

    def get_field_change(self, field_name: str) -> FieldChange | None:
        """Return the
        [`FieldChange`][django_service_specs.mutations.field_change.FieldChange] for
        ``field_name``, or ``None``."""
        for change in self.changes:
            if change.field == field_name:
                return change
        return None

    def get_child_change(self, relation: str) -> ChildCollectionChange | None:
        """Return the
        [`ChildCollectionChange`][django_service_specs.mutations.child_collection_change.ChildCollectionChange]
        for ``relation``, or ``None``."""
        for change in self.children:
            if change.relation == relation:
                return change
        return None

    def get_relation_change(self, relation: str) -> RelatedObjectChange | None:
        """Return the
        [`RelatedObjectChange`][django_service_specs.mutations.related_object_change.RelatedObjectChange]
        for ``relation``, or ``None``."""
        for change in self.relations:
            if change.relation == relation:
                return change
        return None

    def __bool__(self) -> bool:
        return bool(self.changes or any(self.children) or any(self.relations))
