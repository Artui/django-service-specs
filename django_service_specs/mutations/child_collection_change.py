"""``ChildCollectionChange`` — per-collection deltas from a nested write."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ChildCollectionChange:
    """What a nested write did to one relation that holds a collection.

    Carried in ``ChangeResult.children``, one entry per collection declared in
    ``relations=``: a reverse-FK
    [`ChildSpec`][django_service_specs.relations.child_spec.ChildSpec], a
    [`GenericRelationSpec`][django_service_specs.relations.generic_relation_spec.GenericRelationSpec]
    or a
    [`ManyToManySpec`][django_service_specs.relations.many_to_many_spec.ManyToManySpec].
    A relation holding one row reports a
    [`RelatedObjectChange`][django_service_specs.mutations.related_object_change.RelatedObjectChange]
    instead. The tuples hold row **primary keys**:

    - **``created``** — rows inserted.
    - **``updated``** — rows that already existed, matched by the spec's
      ``match_key`` and written: among the parent's own rows for a child or
      generic collection, inside ``scope`` for a many-to-many.
    - **``deleted``** — rows the relation let go and deleted.
    - **``unlinked``** — rows the relation let go and kept, with their link to
      the parent set to ``None``.
    - **``removed``** — rows handed to the spec's ``delete_service``.
      Deliberately a fifth tuple rather than a reuse of ``deleted``: once a
      service owns the row, the loop no longer knows whether it was deleted,
      archived, unlinked or left standing, and folding those into ``deleted``
      would report a guess as fact. What the loop does know is that the row
      left the relation and a service decided the rest.

    Whether a row let go is ``deleted`` or ``unlinked`` is the spec's ``orphan``
    ([`RelationOrphan`][django_service_specs.relations.relation_orphan.RelationOrphan]),
    not the column alone: ``"delete"`` always deletes; ``"unlink"`` always unlinks,
    and is refused where the link cannot hold ``NULL``; ``"auto"``, the default,
    unlinks when it can — both columns, for a generic relation — and deletes when
    it cannot. A many-to-many target is shared, so a member ``"replace"`` drops
    only loses its membership and is always ``unlinked``; that kind has no
    ``orphan`` and no ``delete_service``, and its ``deleted`` and ``removed`` stay
    empty.

    ``updated`` records every matched row the write ran through
    ``update_from_input`` or the spec's ``update_service``, whether or not that
    row's own columns actually changed.
    """

    relation: str
    created: tuple[Any, ...] = field(default_factory=tuple)
    updated: tuple[Any, ...] = field(default_factory=tuple)
    deleted: tuple[Any, ...] = field(default_factory=tuple)
    unlinked: tuple[Any, ...] = field(default_factory=tuple)
    removed: tuple[Any, ...] = field(default_factory=tuple)

    def __bool__(self) -> bool:
        return bool(self.created or self.updated or self.deleted or self.unlinked or self.removed)


__all__ = ["ChildCollectionChange"]
