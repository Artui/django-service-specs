"""``ReverseOneToOneSpec`` — the singular-row variant of the children loop."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import KW_ONLY, dataclass
from typing import Any, ClassVar

from django.db.models import Model

from django_service_specs.relations.relation_orphan import RelationOrphan
from django_service_specs.relations.relation_phase import RelationPhase
from django_service_specs.relations.relation_spec import RelationSpec
from django_service_specs.relations.utils import (
    validate_relation_orphan,
    validate_relation_services,
)


@dataclass(frozen=True)
class ReverseOneToOneSpec(RelationSpec):
    """How to persist a **reverse** one-to-one — the row that points *back*.

    The other side of a ``OneToOneField``: the column lives on the related row
    (``Profile.author``) and the parent (``Author``) reaches at most one of them through
    the reverse accessor. So it is the
    [`ChildSpec`][django_service_specs.relations.child_spec.ChildSpec] loop minus the
    collection, written in ``RelationPhase.REVERSE`` once the parent has a primary key
    to point at.

    Declared in ``relations={accessor_name: ReverseOneToOneSpec(...)}``, where
    the name is the parent's reverse accessor (``relations={"profile": ...}``
    for ``Author.profile``). The value at ``data[accessor_name]`` reads three
    ways. **Omitted** leaves the relation untouched. **``None``** removes the
    existing row, if any, by the ``orphan`` rule below — unlike a forward
    relation, this row *is* the parent's, so clearing the relation has to do
    something about it. **A mapping** updates the row when the parent already
    has one, and creates and links one when it does not.

    The existing row is found by querying ``fk`` rather than through the reverse
    accessor, so whatever the accessor had cached is a different Python object
    from the one that gets written. Each of the three cases leaves the parent
    agreeing with the write — pointed at the written row, or cleared where the
    row was removed — so the returned instance does not read a pre-write row.

    There is no ``match_key`` and no ``scope`` — the parent owns at most one row
    here, so the relation itself is the match — and no ``mode``: a one-row
    relation has no orphans beyond the ``None`` case, which is explicit.

    Attributes:
        model: The related model class.
        fk: The name of that model's field pointing at the parent (``"author"``
            for ``Profile.author``). Set automatically on creation, and the
            field whose nullability decides unlink-versus-delete by default.
        orphan: What removing the row *does*, by
            [`ChildSpec`][django_service_specs.relations.child_spec.ChildSpec]'s rule: ``"auto"`` (the
            default) derives it from ``fk`` — **unlinked** when that field is
            nullable (like ``on_delete=SET_NULL``), **deleted** when it is not
            (like ``CASCADE``) — while ``"unlink"`` / ``"delete"`` state it
            instead, and ``"unlink"`` against a non-nullable ``fk`` raises
            ``ImproperlyConfigured`` at write time.
            It covers both removals there are: the ``None`` case above and the
            delete cascade.
        field_map: Forwarded to the row's own ``create_from_input`` /
            ``update_from_input`` call. It shapes that **write** and nothing
            else: the row is found through ``fk`` and the parent link is
            written onto it raw, neither of them reading this map.
        exclude_fields: Forwarded likewise. Shaping configures the row's
            **write** only; the row itself is found through ``fk``, and a
            matched row's primary key is dropped from the write for you.
        m2m: Forwarded likewise.
        relations: Forwarded likewise — the row's own relations, of any kind.
        create_service: Optional service replacing that call for the row, with
            the contract [`ChildSpec`][django_service_specs.relations.child_spec.ChildSpec] states: it
            receives ``parent``, and its ``data`` already carries the ``fk``.
            Declaring it alongside the row-shaping fields above raises at
            construction.
        update_service: The same; returning ``None`` means "use the in-memory
            instance".
        delete_service: Replaces the unlink-or-delete rule above, so the outcome
            is reported as ``"removed"`` — the only thing still known — and an
            explicit ``orphan`` beside it raises.
    """

    write_phase: ClassVar[RelationPhase] = RelationPhase.REVERSE

    model: type[Model]
    fk: str
    # Every option is keyword-only, for the reason ``RelationSpec`` gives.
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
        validate_relation_services(
            label="ReverseOneToOneSpec",
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


__all__ = ["ReverseOneToOneSpec"]
