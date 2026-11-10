from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from django.core.exceptions import ImproperlyConfigured
from django.db.models import Model

from django_service_specs.types.relation_mode import RelationMode
from django_service_specs.types.relation_orphan import RelationOrphan

VALID_RELATION_MODES = tuple(mode.value for mode in RelationMode)


def validate_relation_mode(mode: str, *, label: str) -> None:
    """Reject a ``mode`` that is neither ``"replace"`` nor ``"merge"``."""
    if mode not in VALID_RELATION_MODES:
        raise ValueError(f"{label}.mode must be one of {VALID_RELATION_MODES}; got {mode!r}.")


VALID_RELATION_ORPHANS = tuple(orphan.value for orphan in RelationOrphan)


def validate_relation_orphan(orphan: str, *, delete_service: Any, label: str) -> None:
    """Check ``orphan``, and refuse it beside the service that would silence it."""
    if orphan not in VALID_RELATION_ORPHANS:
        raise ValueError(f"{label}.orphan must be one of {VALID_RELATION_ORPHANS}; got {orphan!r}.")
    if delete_service is None or orphan == RelationOrphan.AUTO:
        return
    raise ImproperlyConfigured(
        f"{label}: orphan={RelationOrphan(orphan).value!r} declared alongside delete_service. "
        "The service replaces the unlink-or-delete rule entirely, so the flag would decide "
        "nothing. Dispose of the row in the service, or drop the service and let orphan= say "
        "what happens to it."
    )


class _RowWriteSpec(Protocol):
    """The six fields of a relation spec that say who writes its rows, and how."""

    @property
    def create_service(self) -> Callable[..., Any] | None: ...
    @property
    def update_service(self) -> Callable[..., Any] | None: ...
    @property
    def field_map(self) -> Mapping[str, str] | None: ...
    @property
    def exclude_fields(self) -> Sequence[str] | None: ...
    @property
    def m2m(self) -> Mapping[str, Any] | Callable[[Any], Mapping[str, Any]] | None: ...
    @property
    def relations(self) -> Mapping[str, Any] | None: ...


def validate_relation_services(spec: _RowWriteSpec, *, label: str) -> None:
    """Refuse a relation spec that declares a row service *and* row shaping."""
    services: dict[str, Any] = {
        "create_service": spec.create_service,
        "update_service": spec.update_service,
    }
    declared_services: list[str] = sorted(name for name, value in services.items() if value)
    if not declared_services:
        return
    shaping: dict[str, Any] = {
        "field_map": spec.field_map,
        "exclude_fields": spec.exclude_fields,
        "m2m": spec.m2m,
        "relations": spec.relations,
    }
    declared_shaping: list[str] = sorted(name for name, value in shaping.items() if value)
    if not declared_shaping:
        return
    raise ImproperlyConfigured(
        f"{label}: {', '.join(declared_services)} declared alongside "
        f"{', '.join(declared_shaping)}. A row service replaces the helper call "
        "that those configure, so they would be silently ignored. Drop them and "
        "let the service shape the row, or drop the service and let the helper "
        "write it. Reconciliation (fk / match_key / mode / scope / orphan "
        "handling) stays with the spec either way."
    )


def pk_input_targets(model: type[Model]) -> frozenset[str]:
    """The names an incoming row can use to mean ``model``'s primary key."""
    return frozenset({"pk", model._meta.pk.name, model._meta.pk.attname})


def validate_pk_field_map(
    *,
    label: str,
    model: type[Model],
    match_key: str,
    field_map: Mapping[str, str] | None,
) -> None:
    """Refuse a ``field_map`` that renames an input key onto the primary key."""
    targets: frozenset[str] = pk_input_targets(model)
    if match_key not in targets:
        return
    mapped: list[str] = sorted(src for src, dest in (field_map or {}).items() if dest in targets)
    if not mapped:
        return
    raise ImproperlyConfigured(
        f"{label}: field_map renames {', '.join(repr(name) for name in mapped)} onto the "
        f"primary key of {model.__name__}, which match_key={match_key!r} also matches on. "
        "Matching reads the row as it arrived and does not apply field_map, so a payload "
        "using the mapped name can never match, while the primary-key guard does apply it "
        "and refuses the row. Send the key under a name match_key reads, or match on a "
        "field the mapping does not rename."
    )
