from __future__ import annotations

from typing import ClassVar

from django_service_specs.types.relation_phase import RelationPhase


class RelationSpec:
    """What the nested-write driver needs from a relation spec: its phase."""

    write_phase: ClassVar[RelationPhase]


__all__ = ["RelationSpec"]
