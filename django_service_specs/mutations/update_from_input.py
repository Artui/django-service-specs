"""Apply partial input to an existing instance and persist only changed fields."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.mutations.change_result import ChangeResult, ModelT
from django_service_specs.mutations.nested_writes import update_instance
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
    that list so they are refreshed alongside the mutation, and so are a
    changed ``ImageField``'s ``width_field`` and ``height_field``, which
    setting the image wrote on the instance. Pass ``False`` to
    perform a full save, or an explicit list to control exactly which columns
    are written (no auto-injection in that case).

    A file field is written as a ``ModelForm`` writes it, through the model
    field's ``save_form_data``: a file replaces the one the row holds, ``None`` keeps it, and ``False``,
    a form's value for a cleared file, leaves no file, reported as a change to ``""``.
    An upload, or any ``File`` that is not one a row holds, is always written and reported,
    even under the name of the file it replaces, since a name says nothing of the content;
    the held file handed back as itself is no change.

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
    return update_instance(
        instance,
        data,
        field_map=field_map,
        exclude_fields=exclude_fields,
        m2m=m2m,
        update_fields=update_fields,
        relations=relations,
        context=context,
    )
