"""Construct, save, and post-process a new model instance from input data."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.mutations.change_result import ChangeResult, ModelT
from django_service_specs.mutations.nested_writes import create_instance
from django_service_specs.relations.relation_spec import RelationSpec


def create_from_input(
    model: type[ModelT],
    data: Any,
    *,
    field_map: dict[str, str] | None = None,
    exclude_fields: list[str] | None = None,
    m2m: dict[str, Any] | None = None,
    relations: Mapping[str, RelationSpec] | None = None,
    context: Mapping[str, Any] | None = None,
) -> ChangeResult[ModelT]:
    """Build, ``save()``, and return a fresh instance of ``model``.

    Regular fields come from ``data`` (a dataclass, dict, or object with ``__dict__``).

    A file field is written as a ``ModelForm`` writes it, through the model
    field's ``save_form_data``: a file is stored, ``None`` leaves the field to the model, and ``False``,
    a form's value for a cleared file, stores no file.

    ``m2m`` maps a many-to-many attribute to the rows it should hold — instances or
    primary keys of rows that **already exist** — and ``set()``s them after the save;
    it creates nothing. A
    [`ManyToManySpec`][django_service_specs.relations.many_to_many_spec.ManyToManySpec]
    in ``relations`` does the other job: it writes the target rows *from the payload*,
    creating or updating each, and then links them. A relation named by both is
    refused, since it would be written twice and keep whichever ran last.

    ``relations`` maps a relation name to the spec for its kind, and is the one map for
    every kind — a reverse-FK
    [`ChildSpec`][django_service_specs.relations.child_spec.ChildSpec] included. The
    nested payload is read from ``data[relation]`` and written in the order the kind
    dictates, not the order the map is spelled in (see
    [`RelationPhase`][django_service_specs.types.relation_phase.RelationPhase]).
    Keep the whole call inside the service's atomic block.

    ``context`` is an **opaque** mapping forwarded verbatim down the tree, into the pool
    of every row service a relation spec declares and of every ``scope`` callable. This
    helper never reads it — it exists so per-row work downstream can see the acting
    caller. A service opts in by handing on the pool it was called with,
    ``context=kwargs``. A catch-all is never handed the call's context, so a
    service whose nested callables should see it names ``call_context`` and
    hands it on beside the pool, as ``create_model``'s service does."""
    return create_instance(
        model,
        data,
        field_map=field_map,
        exclude_fields=exclude_fields,
        m2m=m2m,
        relations=relations,
        context=context,
    )
