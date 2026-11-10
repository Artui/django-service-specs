from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import KW_ONLY, dataclass
from typing import Any, ClassVar

from django.db.models import Model

from django_service_specs.relations.relation_spec import RelationSpec
from django_service_specs.relations.utils import (
    validate_pk_field_map,
    validate_relation_mode,
    validate_relation_orphan,
    validate_relation_services,
)
from django_service_specs.types.relation_mode import RelationMode
from django_service_specs.types.relation_orphan import RelationOrphan
from django_service_specs.types.relation_phase import RelationPhase


@dataclass(frozen=True)
class GenericRelationSpec(RelationSpec):
    """How to persist a ``GenericRelation`` — a collection linked by content type."""

    write_phase: ClassVar[RelationPhase] = RelationPhase.GENERIC

    model: type[Model]
    _: KW_ONLY
    content_type_field: str = "content_type"
    object_id_field: str = "object_id"
    match_key: str = "pk"
    mode: RelationMode | str = RelationMode.REPLACE
    orphan: RelationOrphan | str = RelationOrphan.AUTO
    field_map: dict[str, str] | None = None
    exclude_fields: list[str] | None = None
    m2m: Mapping[str, Any] | Callable[[Any], Mapping[str, Any]] | None = None
    relations: Mapping[str, RelationSpec] | None = None
    create_service: Callable[..., Any] | None = None
    update_service: Callable[..., Any] | None = None
    delete_service: Callable[..., Any] | None = None

    def __post_init__(self) -> None:
        validate_pk_field_map(
            label="GenericRelationSpec",
            model=self.model,
            match_key=self.match_key,
            field_map=self.field_map,
        )
        validate_relation_mode(self.mode, label="GenericRelationSpec")
        validate_relation_orphan(
            self.orphan, delete_service=self.delete_service, label="GenericRelationSpec"
        )
        validate_relation_services(self, label="GenericRelationSpec")


__all__ = ["GenericRelationSpec"]
