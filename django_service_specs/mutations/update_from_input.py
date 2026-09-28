"""Apply partial input to an existing instance and persist only changed fields."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.mutations.change_result import ChangeResult, ModelT
from django_service_specs.mutations.utils import (
    _auto_now_field_names,
    apply_forward_relations,
    apply_m2m,
    apply_relations,
    coerce_to_dict,
    diff_attrs,
    extract_relation_data,
    filter_input,
    m2m_changes,
    reject_m2m_overlap,
    relation_map,
    resolve_update_fields,
    sync_relation_cache,
)
from django_service_specs.relations.relation_spec import RelationSpec


def update_from_input(
    instance: ModelT,
    data: Any,
    *,
    field_map: dict[str, str] | None = None,
    exclude_fields: list[str] | None = None,
    m2m: dict[str, Any] | None = None,
    update_fields: bool | list[str] = True,
    relations: Mapping[str, RelationSpec] | None = None,
    context: Mapping[str, Any] | None = None,
) -> ChangeResult[ModelT]:
    """Update ``instance`` with values from ``data``, persisting only deltas.

    By default (``update_fields=True``), the save call uses
    ``update_fields=<changed>`` to write the minimal set of columns.
    ``auto_now=True`` fields (e.g. ``updated_at``) are automatically added to
    that list so they are refreshed alongside the mutation. Pass ``False`` to
    perform a full save, or an explicit list to control exactly which columns
    are written (no auto-injection in that case).

    ``m2m`` assigns many-to-many rows that already exist, and only where the set
    of primary keys differs from the current one;
    [`ManyToManySpec`][django_service_specs.relations.many_to_many_spec.ManyToManySpec]
    in ``relations`` writes the target rows from the payload instead. A relation named
    by both is refused rather than written twice.

    ``relations`` maps a relation name to the spec for its kind, one map for
    every kind. The nested payload from ``data[relation]`` is
    reconciled with what is already there — create / update / orphan-remove per
    the spec — and a relation the input omits is left untouched. Kinds are
    written in the order their class dictates, so a forward foreign key is
    resolved before this instance is saved and the assignment rides the same
    diff and ``update_fields`` path as any other column. Keep the call inside
    the service's atomic block.

    A relation that was written stays readable off the returned instance. The
    one-row kinds resolve their row by re-querying, so the parent's cached
    related object is replaced with the row that was written — and dropped where
    the write removed it — rather than left holding pre-write values.

    ``context`` is an **opaque** mapping forwarded verbatim into the pool of every
    row service and ``scope`` callable the relation specs declare; this
    helper never reads it. See
    [`create_from_input`][django_service_specs.mutations.create_from_input.create_from_input].
    """
    relation_specs = relation_map(relations)
    reject_m2m_overlap(m2m, relation_specs)
    raw: dict[str, Any] = coerce_to_dict(data)
    relation_data: dict[str, Any] = extract_relation_data(raw, relation_specs)
    new_values: dict[str, Any] = filter_input(
        raw,
        field_map=field_map,
        exclude_fields=exclude_fields,
    )
    forward_values, forward_changes = apply_forward_relations(
        relation_data, relation_specs, context=context
    )
    new_values.update(forward_values)
    field_changes = diff_attrs(instance, new_values)
    for change in field_changes:
        setattr(instance, change.field, change.new)
    for relation, target in forward_values.items():
        sync_relation_cache(instance, relation, target)
    m2m_field_changes, to_apply = m2m_changes(instance, m2m, created=False)
    changed_field_names: tuple[str, ...] = tuple(change.field for change in field_changes)
    save_fields: list[str] | None = resolve_update_fields(
        update_fields, changed_field_names, _auto_now_field_names(instance)
    )
    if field_changes or update_fields is False:
        if save_fields is None:
            instance.save()
        else:
            instance.save(update_fields=save_fields)
    apply_m2m(instance, to_apply)
    child_changes, related_changes = apply_relations(
        instance, relation_data, relation_specs, created=False, context=context
    )
    return ChangeResult(
        instance=instance,
        created=False,
        changes=field_changes + m2m_field_changes,
        children=child_changes,
        relations=forward_changes + related_changes,
    )
