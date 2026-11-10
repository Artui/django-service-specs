from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import KW_ONLY, dataclass
from typing import Any, ClassVar

from django.db.models import Model

from django_service_specs.relations.relation_spec import RelationSpec
from django_service_specs.relations.utils import (
    validate_relation_orphan,
    validate_relation_services,
)
from django_service_specs.types.relation_orphan import RelationOrphan
from django_service_specs.types.relation_phase import RelationPhase


@dataclass(frozen=True)
class ReverseOneToOneSpec(RelationSpec):
    """How to persist a **reverse** one-to-one — the row that points *back*."""

    write_phase: ClassVar[RelationPhase] = RelationPhase.REVERSE

    model: type[Model]
    fk: str
    _: KW_ONLY
    orphan: RelationOrphan | str = RelationOrphan.AUTO
    field_map: dict[str, str] | None = None
    exclude_fields: list[str] | None = None
    m2m: Mapping[str, Any] | Callable[[Any], Mapping[str, Any]] | None = None
    relations: Mapping[str, RelationSpec] | None = None
    create_service: Callable[..., Any] | None = None
    update_service: Callable[..., Any] | None = None
    delete_service: Callable[..., Any] | None = None

    def __post_init__(self) -> None:
        validate_relation_orphan(
            self.orphan, delete_service=self.delete_service, label="ReverseOneToOneSpec"
        )
        validate_relation_services(self, label="ReverseOneToOneSpec")


__all__ = ["ReverseOneToOneSpec"]
