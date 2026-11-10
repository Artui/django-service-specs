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
    """Outcome of a mutation helper call."""

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
        """The ``FieldChange`` for ``field_name``, or ``None``."""
        for change in self.changes:
            if change.field == field_name:
                return change
        return None

    def get_child_change(self, relation: str) -> ChildCollectionChange | None:
        """The ``ChildCollectionChange`` for ``relation``, or ``None``."""
        for change in self.children:
            if change.relation == relation:
                return change
        return None

    def get_relation_change(self, relation: str) -> RelatedObjectChange | None:
        """The ``RelatedObjectChange`` for ``relation``, or ``None``."""
        for change in self.relations:
            if change.relation == relation:
                return change
        return None

    def __bool__(self) -> bool:
        return bool(self.changes or any(self.children) or any(self.relations))
