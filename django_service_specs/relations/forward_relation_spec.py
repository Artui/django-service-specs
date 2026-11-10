from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import KW_ONLY, dataclass
from typing import Any, ClassVar

from django.db.models import Model, QuerySet

from django_service_specs.relations.relation_spec import RelationSpec
from django_service_specs.relations.utils import (
    validate_pk_field_map,
    validate_relation_services,
)
from django_service_specs.types.relation_phase import RelationPhase


@dataclass(frozen=True)
class ForwardRelationSpec(RelationSpec):
    """How to persist a **forward** relation — a ``ForeignKey`` *or* a ``OneToOneField`` declared
    on the parent itself."""

    write_phase: ClassVar[RelationPhase] = RelationPhase.FORWARD

    model: type[Model]
    _: KW_ONLY
    match_key: str = "pk"
    scope: QuerySet[Any] | Callable[..., QuerySet[Any]] | None = None
    field_map: dict[str, str] | None = None
    exclude_fields: list[str] | None = None
    m2m: Mapping[str, Any] | Callable[[Any], Mapping[str, Any]] | None = None
    relations: Mapping[str, RelationSpec] | None = None
    create_service: Callable[..., Any] | None = None
    update_service: Callable[..., Any] | None = None

    def __post_init__(self) -> None:
        validate_pk_field_map(
            label="ForwardRelationSpec",
            model=self.model,
            match_key=self.match_key,
            field_map=self.field_map,
        )
        validate_relation_services(self, label="ForwardRelationSpec")


__all__ = ["ForwardRelationSpec"]
