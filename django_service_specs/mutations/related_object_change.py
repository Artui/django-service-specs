from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django_service_specs.types.relation_outcome import RelationOutcome


@dataclass(frozen=True)
class RelatedObjectChange:
    """The delta for a relation that holds **one** row, not a collection."""

    relation: str
    outcome: RelationOutcome = RelationOutcome.UNTOUCHED
    pk: Any = None

    def __bool__(self) -> bool:
        return self.outcome is not RelationOutcome.UNTOUCHED


__all__ = ["RelatedObjectChange"]
