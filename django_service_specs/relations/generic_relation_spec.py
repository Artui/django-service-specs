"""``GenericRelationSpec`` — rows linked to the parent by a content type."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import KW_ONLY, dataclass
from typing import Any, ClassVar

from django.db.models import Model

from django_service_specs.relations.relation_mode import RelationMode
from django_service_specs.relations.relation_orphan import RelationOrphan
from django_service_specs.relations.relation_phase import RelationPhase
from django_service_specs.relations.relation_spec import RelationSpec
from django_service_specs.relations.utils import (
    validate_pk_field_map,
    validate_relation_mode,
    validate_relation_orphan,
    validate_relation_services,
)


@dataclass(frozen=True)
class GenericRelationSpec(RelationSpec):
    """How to persist a ``GenericRelation`` — a collection linked by content type.

    The reverse-FK collection with the foreign key replaced by a pair of columns: a
    ``ForeignKey`` to ``ContentType`` saying *which model* the row belongs to, and an id
    column saying *which row*. It reconciles exactly as
    [`ChildSpec`][django_service_specs.relations.child_spec.ChildSpec] does — matched
    inside the parent's own accessor, so no ``scope=`` is needed or accepted — and is
    written in ``RelationPhase.GENERIC``, once the parent's ``save()`` has given it both
    a content type and a primary key.

    Declared in ``relations={accessor_name: GenericRelationSpec(...)}``, where
    the name is the ``GenericRelation`` declared on the parent
    (``relations={"attachments": ...}`` for ``Catalog.attachments``). A
    relation the input omits is untouched; an explicit ``[]`` in ``"replace"``
    mode empties it.

    **This kind needs ``django.contrib.contenttypes`` in ``INSTALLED_APPS``**,
    and nothing else in the library does. Declaring the spec is always safe;
    *writing* one without the app installed raises
    ``ImproperlyConfigured`` naming the remedy.

    Attributes:
        model: The related model class — the one carrying the content-type and
            id columns, e.g. ``Attachment``.
        content_type_field: Name of the content-type column, defaulting to
            Django's own ``"content_type"``.
        object_id_field: Name of the id column, defaulting to ``"object_id"``.
            Both mirror the ``GenericRelation`` arguments of the same name; set
            them when the model spells the columns differently.
        match_key: The field pairing an incoming row with an existing one
            (default ``"pk"``), read inside the parent's own accessor. Read off the incoming row as an input key
            and off the lookup as a model field, so ``field_map`` may not
            rename anything onto the primary key while ``match_key`` matches
            on it — that combination raises at construction, on the terms
            [`ChildSpec`][django_service_specs.relations.child_spec.ChildSpec] states.
        mode: ``"replace"`` (the default) removes the rows the incoming set
            leaves out, ``"merge"`` upserts only.
        orphan: What removing a row *does* —
            [`ChildSpec`][django_service_specs.relations.child_spec.ChildSpec]'s rule applied to the
            pair of link columns rather than to one, since half a link is not a
            state the relation has a meaning for. ``"auto"`` (the default)
            **unlinks** (both columns set to ``None``) when both are nullable
            and **deletes** otherwise; ``"unlink"`` and ``"delete"`` state it
            instead of deriving it, and ``"unlink"`` raises at write time unless
            both columns can hold ``NULL``. The rule also governs the
            delete cascade ([`delete_relations`][django_service_specs.mutations.delete_relations.delete_relations]).
        field_map: Forwarded to the row's own ``create_from_input`` /
            ``update_from_input`` call. It shapes that **write** and nothing
            else: matching and the primary-key guard both read the row
            exactly as it arrived, so renaming a key here does not change
            which row the payload matches.
        exclude_fields: Forwarded likewise. Excluding the ``match_key`` does not stop the row
            matching on it, and a matched row's primary key is dropped from
            the write for you, so there is no need to name it here.
        m2m: Forwarded likewise.
        relations: Forwarded likewise — the row's own relations, of any kind.
        create_service: Optional service replacing that call, with the contract
            [`ChildSpec`][django_service_specs.relations.child_spec.ChildSpec] states; its ``data``
            already carries both link columns. Declaring it alongside the
            row-shaping fields above raises at construction.
        update_service: The same; returning ``None`` means "use the in-memory
            instance".
        delete_service: Replaces the unlink-or-delete rule above, so the outcome
            is reported as ``"removed"`` and an explicit ``orphan`` beside it
            raises.
    """

    write_phase: ClassVar[RelationPhase] = RelationPhase.GENERIC

    model: type[Model]
    # Every option is keyword-only, for the reason ``RelationSpec`` gives.
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
        validate_relation_services(
            label="GenericRelationSpec",
            services={
                "create_service": self.create_service,
                "update_service": self.update_service,
            },
            shaping={
                "field_map": self.field_map,
                "exclude_fields": self.exclude_fields,
                "m2m": self.m2m,
                "relations": self.relations,
            },
        )


__all__ = ["GenericRelationSpec"]
