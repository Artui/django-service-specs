"""``RelationOutcome`` — what a nested write did to one singular relation."""

from __future__ import annotations

from enum import Enum


class RelationOutcome(str, Enum):
    """The single fact a
    [`RelatedObjectChange`][django_service_specs.mutations.related_object_change.RelatedObjectChange]
    reports.

    A collection reports five tuples of primary keys, which is the honest shape
    for many rows and a poor one for a relation that holds exactly one: every
    tuple would be empty or a one-tuple, and "which of the five is non-empty" is
    a worse way to say what happened than saying it. So only the one-row kinds
    report an outcome — a forward relation and a reverse one-to-one — and a
    collection, many-to-many included, reports its tuples.

    Inheriting from ``str`` keeps the value JSON-serializable and lets a caller
    compare against the plain string, matching
    [`SelectorKind`][django_service_specs.specs.selector_kind.SelectorKind].
    """

    UNTOUCHED = "untouched"
    """Nothing was written to the relation.

    The input omitted it, or set a reverse one-to-one that holds no row to
    ``None``. It is the one outcome for which a
    [`RelatedObjectChange`][django_service_specs.mutations.related_object_change.RelatedObjectChange]
    is falsy.
    """

    CREATED = "created"
    """A new row was written and linked."""

    UPDATED = "updated"
    """An existing row was matched and written."""

    CLEARED = "cleared"
    """A forward relation was set to ``None``.

    The parent's foreign-key column is assigned ``None`` and the row it pointed
    at, if any, is not touched, because a forward target is not owned by the
    parent and may be shared. The change carries no primary key: nothing
    happened to a row. It is reported whether or not the column held a value;
    whether the column moved is ``ChangeResult.changes``' to say.
    """

    UNLINKED = "unlinked"
    """A reverse one-to-one row was kept and its foreign key set to ``None``.

    Mirroring ``on_delete=SET_NULL``. The spec's ``orphan`` decides between this
    and ``DELETED``: ``"unlink"`` always, ``"auto"`` when the foreign key is
    nullable. A member a many-to-many drops is not reported here: that kind is a
    collection, so the member's pk lands in
    [`ChildCollectionChange.unlinked`][django_service_specs.mutations.child_collection_change.ChildCollectionChange].
    """

    DELETED = "deleted"
    """A reverse one-to-one row was deleted.

    Mirroring ``on_delete=CASCADE``. The spec's ``orphan`` decides between this
    and ``UNLINKED``: ``"delete"`` always, whether or not the foreign key could
    have been blanked, and ``"auto"`` when it is not nullable.
    """

    REMOVED = "removed"
    """A row was handed to the spec's ``delete_service``.

    Deliberately not ``DELETED``. Once a service owns the row the loop no
    longer knows whether it was deleted, archived, unlinked or left standing,
    and reporting a guess as fact is worse than reporting the one thing that is
    true: the loop removed the row from the relation and a service decided the
    rest.
    """


__all__ = ["RelationOutcome"]
