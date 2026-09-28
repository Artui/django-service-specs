"""``ChildSpec`` — declarative reverse-FK child-collection write configuration."""

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
class ChildSpec(RelationSpec):
    """How to persist one reverse-FK ("one-to-many") child collection.

    The reverse-FK member of the relation taxonomy: it writes rows whose
    foreign key points back at the parent, so it belongs to
    ``RelationPhase.REVERSE`` and is written after
    the parent's ``save()``.

    Passed in the ``relations={relation_name: ChildSpec(...)}`` map of
    [`create_from_input`][django_service_specs.mutations.create_from_input.create_from_input]
    /
    [`update_from_input`][django_service_specs.mutations.update_from_input.update_from_input]
    (and their async siblings). The incoming child rows are read from
    ``data[relation_name]``; each child is persisted by running it back through
    the same mutation helpers, so scalar / m2m / nested semantics compose
    recursively. The whole parent + children write runs inside
    the service's atomic block; validating the arguments stays with the spec's Validator,
    which dispatch runs before the service — the helper owns persistence only.

    **Pluggable services — the spec owns reconciliation, the service owns the row.**
    Matching, ``mode`` and orphan handling never move into your code; a slot is called
    once per row the loop has already decided about. Each is invoked through
    [`run_service`][django_service_specs.services.run_service.run_service] /
    [`arun_service`][django_service_specs.services.arun_service.arun_service] with
    ``atomic=False``, because the surrounding service's atomic block already wraps the
    whole tree and letting each row open its own would mean a savepoint per row. Each
    receives only the pool keys it declares (the library's usual signature-filtering
    idiom), drawn from the mutation helpers' opaque ``context=`` plus the loop's own
    seeds. Those seeds — ``data`` / ``instance`` / ``parent`` — are applied **after**
    the context, so a context key of the same name cannot outrank them, the precedence
    form of the rule ``RESERVED_POOL_SEEDS`` states for dispatch's pools. In the
    async loops the slot must be an ``async def``: the async path is awaited end to end,
    so a sync one is refused with ``ImproperlyConfigured``, naming the relation and the
    slot, before it runs.

    A declared slot owns that row **entirely**: ``field_map``,
    ``exclude_fields``, ``m2m`` and the nested ``relations`` map configure the
    default mutation-helper call, so a ``create_service`` / ``update_service``
    standing in for it makes them dead configuration.
    Declaring both raises
    ``ImproperlyConfigured`` at construction rather
    than dropping them quietly. ``delete_service`` is exempt — it replaces the
    unlink-or-delete rule, not the helper call, so the cascade still removes a
    row's grandchildren before handing the row over. The spec keeps only what
    it never delegates — which rows exist, which incoming row matches which
    existing one, and what happens to the ones left over.

    Attributes:
        model: The child model class.
        fk: Name of the child's forward foreign-key field pointing at the
            parent (``"author"`` for ``Book.author``). Set automatically on
            created children, and used to resolve the parent's reverse manager.
        match_key: Field used to pair an incoming row with an existing child.
            An incoming row whose ``match_key`` matches an existing child
            updates it; one with no match, or no key, is created. The same name
            is read off both the incoming mapping (``item[match_key]``) and the
            existing instance (``getattr(child, match_key)``), so rows
            keyed by ``"id"`` should set ``match_key="id"``.
            The one name does two jobs — an **input** key on the mapping side,
            a **model field** on the lookup side — which is fine while the two
            agree and is why ``field_map`` may not rename anything onto the
            primary key while ``match_key`` matches on it: there would be no
            single name left to read. That combination raises at construction.
        mode: ``"replace"`` matches incoming to existing, creates new, updates
            matched, and removes orphans (existing children absent from the
            incoming set); ``"merge"`` upserts only and never removes.
        orphan: What removing an orphan *does*, where ``mode`` says whether one
            is removed at all. ``"auto"`` derives it from the schema:
            **unlinked** (its ``fk`` set to ``None``) when the FK is nullable,
            else **deleted**, mirroring ``on_delete=SET_NULL`` vs ``CASCADE``.
            ``"unlink"`` and ``"delete"`` say it outright, for a spec that means
            one of them rather than whichever the column happens to allow — a
            later migration adding ``null=True`` would otherwise turn a
            destructive ``"replace"`` into a non-destructive one with nothing in
            the spec changing. ``"unlink"`` against a non-nullable FK raises
            ``ImproperlyConfigured`` when the
            relation is written, since there is no link to blank. The same rule
            governs the delete cascade
            ([`delete_relations`][django_service_specs.mutations.delete_relations.delete_relations]), which disposes of the same rows.
        field_map: Forwarded to the per-child ``create_from_input`` /
            ``update_from_input`` call, exactly as for the parent. It shapes that **write** and nothing else: matching, the
            primary-key guard and the parent link all read the row exactly as
            it arrived, so renaming a key here does not change which row the
            payload matches.
        exclude_fields: Forwarded to the per-child call, as ``field_map`` is. Excluding the ``match_key`` does not stop the row
            matching on it, and a matched row's primary key is dropped from
            the write for you, so there is no need to name it here.
        m2m: The child's own many-to-many assignments — the per-child analogue
            of the helpers' ``m2m=``, and like it, rows that already exist. A
            static mapping (``{"tags": [tag1, tag2]}``) gives every child the
            same; a callable ``(child_row) -> mapping`` derives them from each
            incoming row.
        relations: The child's own relations, of any kind — a
            ``{relation_name: RelationSpec}`` map applied to each child row
            exactly as the top-level ``relations=`` is applied to the parent,
            so a ``ChildSpec`` here writes grandchildren. Recursion follows the
            declared tree, so depth is bounded by how deeply you nest specs.
        create_service: Per-row service replacing the default mutation-helper
            call, for a child whose write has real behaviour (side effects,
            derived columns, events, an external call). Called as
            ``create_service(*, data, parent, **extras)``, where ``data`` is
            the incoming row with the ``fk`` already pointing at ``parent``,
            since linking the child *is* reconciliation. Must return the
            created row; the loop reads its pk for the delta.
        update_service: The same for updates, called as
            ``update_service(*, instance, data, parent, **extras)``. Returning
            ``None`` means "use the in-memory instance", the helpers'
            convention.
        delete_service: Called as
            ``delete_service(*, instance, parent, **extras)``, replacing the
            unlink-or-delete rule for that row — both for orphan removal and
            for the delete cascade ([`delete_relations`][django_service_specs.mutations.delete_relations.delete_relations]). The
            loop can no longer tell an unlink from a delete, so the pk is
            reported under
            ``ChildCollectionChange.removed``
            rather than guessed into one of the two. It *is* the disposal, so
            declaring it beside an explicit ``orphan`` raises at construction:
            the flag would decide nothing.
    """

    write_phase: ClassVar[RelationPhase] = RelationPhase.REVERSE

    model: type[Model]
    fk: str
    # Every option is keyword-only, for the reason ``RelationSpec`` gives.
    _: KW_ONLY
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
            label="ChildSpec",
            model=self.model,
            match_key=self.match_key,
            field_map=self.field_map,
        )
        validate_relation_mode(self.mode, label="ChildSpec")
        validate_relation_orphan(self.orphan, delete_service=self.delete_service, label="ChildSpec")
        validate_relation_services(
            label="ChildSpec",
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


__all__ = ["ChildSpec"]
