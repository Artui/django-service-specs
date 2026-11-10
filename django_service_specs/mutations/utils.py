from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import fields, is_dataclass
from typing import Any, cast

from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist, ValidationError
from django.core.files.base import File
from django.db.models import FileField, ImageField, Model
from django.db.models.fields.files import FieldFile

from django_service_specs.mutations.child_collection_change import ChildCollectionChange
from django_service_specs.mutations.field_change import FieldChange
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.relations.child_spec import ChildSpec
from django_service_specs.relations.generic_relation_spec import GenericRelationSpec
from django_service_specs.relations.relation_spec import RelationSpec
from django_service_specs.services.service_validation_error import ServiceValidationError
from django_service_specs.types.relation_phase import RelationPhase
from django_service_specs.types.unset import UNSET
from django_service_specs.types.utils import CALL_CONTEXT


def coerce_to_dict(data: Any) -> dict[str, Any]:
    """Normalize input ``data`` to a dict mapping field name to value."""
    if data is None:
        return {}
    if isinstance(data, dict):
        return dict(data)
    if is_dataclass(data) and not isinstance(data, type):
        return {f.name: getattr(data, f.name) for f in fields(data) if f.init}
    if hasattr(data, "__dict__"):
        return dict(vars(data))
    raise TypeError(
        f"Cannot coerce input of type {type(data).__name__!r} to a dict; "
        "expected None, a dict, a dataclass instance, or an object with __dict__."
    )


def filter_input(
    raw: dict[str, Any],
    *,
    field_map: dict[str, str] | None,
    exclude_fields: list[str] | None,
) -> dict[str, Any]:
    """Apply ``field_map`` and ``exclude_fields``, dropping ``UNSET`` values."""
    excluded: set[str] = set(exclude_fields or ())
    result: dict[str, Any] = {}
    mapping: dict[str, str] = field_map or {}
    for key, value in raw.items():
        if value is UNSET:
            continue
        if key in excluded:
            continue
        result[mapping.get(key, key)] = value
    return result


def safe_getattr(instance: Model, attr: str) -> Any:
    """``getattr`` that returns ``UNSET`` for unset relations or missing attrs."""
    try:
        return getattr(instance, attr, UNSET)
    except ObjectDoesNotExist:
        return UNSET


def diff_attrs(
    instance: Model,
    new_values: dict[str, Any],
) -> tuple[FieldChange, ...]:
    """Return the subset of ``new_values`` whose value differs from current."""
    changes: list[FieldChange] = []
    for attr, new_value in new_values.items():
        old_value: Any = safe_getattr(instance, attr)
        if (isinstance(new_value, File) and not isinstance(new_value, FieldFile)) or (
            old_value != new_value
        ):
            changes.append(FieldChange(field=attr, old=old_value, new=new_value))
    return tuple(changes)


def file_fields(model: type[Model]) -> dict[str, FileField]:
    """``model``'s file fields, ``ImageField`` included, by name."""
    return {
        field.name: field for field in model._meta.concrete_fields if isinstance(field, FileField)
    }


def form_values(model: type[Model], values: dict[str, Any]) -> dict[str, Any]:
    """``values`` with each file field's read as a ``ModelForm`` writes it."""
    files = file_fields(model)
    read: dict[str, Any] = {}
    for attr, value in values.items():
        if attr in files:
            if value is None:
                continue
            value = value or ""
        read[attr] = value
    return read


def assign_changed_values(instance: Model, values: dict[str, Any]) -> tuple[FieldChange, ...]:
    """Set on ``instance`` each of ``values`` that differs from what it holds, and return those."""
    changes = diff_attrs(instance, form_values(type(instance), values))
    write_values(instance, {change.field: change.new for change in changes})
    return changes


def split_file_values(
    model: type[Model], values: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """``values`` as two maps: the file fields' and every other one's."""
    files = file_fields(model)
    plain = {attr: value for attr, value in values.items() if attr not in files}
    return plain, {attr: value for attr, value in values.items() if attr in files}


def write_values(instance: Model, values: dict[str, Any]) -> None:
    """Set each of ``values`` on ``instance``, a file field's through ``save_form_data``."""
    files = file_fields(type(instance))
    for attr, value in values.items():
        field = files.get(attr)
        if field is None:
            setattr(instance, attr, value)
        else:
            field.save_form_data(instance, value)


def m2m_current_pks(instance: Model, attr: str) -> list[Any]:
    """Return primary keys of the current many-to-many members for ``attr``."""
    manager: Any = getattr(instance, attr)
    return list(manager.values_list("pk", flat=True))


async def am2m_current_pks(instance: Model, attr: str) -> list[Any]:
    """Async variant of ``m2m_current_pks``."""
    manager: Any = getattr(instance, attr)
    return [pk async for pk in manager.values_list("pk", flat=True)]


def m2m_target_pks(value: Any) -> list[Any]:
    """Best-effort extraction of primary keys from an M2M assignment value."""
    if value is None:
        return []
    return [item.pk if isinstance(item, Model) else item for item in value]


def m2m_changes(
    instance: Model,
    m2m: dict[str, Any] | None,
    *,
    created: bool,
) -> tuple[tuple[FieldChange, ...], dict[str, Any]]:
    """``(changes, to_apply)`` — everything on create, only differences on update."""
    if not m2m:
        return ((), {})
    changes: list[FieldChange] = []
    to_apply: dict[str, Any] = {}
    for attr, value in m2m.items():
        new_pks: list[Any] = m2m_target_pks(value)
        if created:
            changes.append(FieldChange(field=attr, old=UNSET, new=value))
            to_apply[attr] = value
            continue
        old_pks: list[Any] = m2m_current_pks(instance, attr)
        if sorted(old_pks, key=repr) != sorted(new_pks, key=repr):
            changes.append(FieldChange(field=attr, old=old_pks, new=value))
            to_apply[attr] = value
    return (tuple(changes), to_apply)


async def am2m_changes(
    instance: Model,
    m2m: dict[str, Any] | None,
    *,
    created: bool,
) -> tuple[tuple[FieldChange, ...], dict[str, Any]]:
    """Async variant of ``m2m_changes``."""
    if not m2m:
        return ((), {})
    changes: list[FieldChange] = []
    to_apply: dict[str, Any] = {}
    for attr, value in m2m.items():
        new_pks: list[Any] = m2m_target_pks(value)
        if created:
            changes.append(FieldChange(field=attr, old=UNSET, new=value))
            to_apply[attr] = value
            continue
        old_pks: list[Any] = await am2m_current_pks(instance, attr)
        if sorted(old_pks, key=repr) != sorted(new_pks, key=repr):
            changes.append(FieldChange(field=attr, old=old_pks, new=value))
            to_apply[attr] = value
    return (tuple(changes), to_apply)


def _normalize_m2m_value(value: Any) -> list[Any]:
    """Coerce a m2m assignment value to a concrete list (``None`` → ``[]``)."""
    if value is None:
        return []
    return list(value)


def apply_m2m(instance: Model, to_apply: dict[str, Any]) -> None:
    """Set each ``to_apply`` value on the instance's m2m manager (sync)."""
    for attr, value in to_apply.items():
        manager: Any = getattr(instance, attr)
        manager.set(_normalize_m2m_value(value))


async def aapply_m2m(instance: Model, to_apply: dict[str, Any]) -> None:
    """Set each ``to_apply`` value on the instance's m2m manager (async)."""
    for attr, value in to_apply.items():
        manager: Any = getattr(instance, attr)
        await manager.aset(_normalize_m2m_value(value))


def changes_for_create(new_values: dict[str, Any]) -> tuple[FieldChange, ...]:
    """Build ``FieldChange`` entries for every assigned create field."""
    return tuple(
        FieldChange(field=attr, old=UNSET, new=value) for attr, value in new_values.items()
    )


def auto_now_field_names(instance: Model) -> tuple[str, ...]:
    """Return the names of all ``auto_now=True`` fields on the model."""
    return tuple(
        f.name for f in instance._meta.concrete_fields if hasattr(f, "auto_now") and f.auto_now
    )


def dimension_field_names(instance: Model, changed: tuple[str, ...]) -> tuple[str, ...]:
    """The ``width_field`` and ``height_field`` of each image field in ``changed``."""
    files = file_fields(type(instance))
    names: list[str] = []
    for attr in changed:
        field = files.get(attr)
        if isinstance(field, ImageField):
            image: Any = field
            names.extend(name for name in (image.width_field, image.height_field) if name)
    return tuple(names)


def resolve_update_fields(
    update_fields: bool | list[str],
    changed: tuple[str, ...],
    derived_fields: tuple[str, ...] = (),
) -> list[str] | None:
    """Map the public ``update_fields`` argument to a ``save()``-compatible list."""
    if update_fields is True:
        fields = list(changed)
        if fields:
            for f in derived_fields:
                if f not in fields:
                    fields.append(f)
        return fields or None
    if update_fields is False:
        return None
    return list(update_fields)


# --- the relation taxonomy: one map, one ordering rule -------------------

# The phases written *after* the parent's save, in the order they run. Stated
# once, here: every call site (create and update, sync and async) reads it from
# this tuple, so the four paths cannot drift.
POST_SAVE_PHASES: tuple[RelationPhase, ...] = (
    RelationPhase.REVERSE,
    RelationPhase.GENERIC,
    RelationPhase.M2M,
)


def relation_map(relations: Mapping[str, RelationSpec] | None) -> dict[str, RelationSpec]:
    """A ``relations=`` map as a plain ``dict``, refusing any value that is not a spec."""
    specs: dict[str, RelationSpec] = dict(relations or {})
    for name, spec in specs.items():
        if not isinstance(spec, RelationSpec):
            raise ImproperlyConfigured(
                f"relations[{name!r}] is a {type(spec).__name__}, which is not a "
                "relation spec. Declare the relation with the spec class for its "
                "kind, so the write order can be read off the class."
            )
    return specs


def reject_m2m_overlap(
    m2m: Mapping[str, Any] | None,
    relations: Mapping[str, RelationSpec],
) -> None:
    """Refuse a relation written by ``m2m=`` and by a relation spec at once."""
    for name in m2m or {}:
        if name in relations:
            raise ImproperlyConfigured(
                f"{name!r} is declared both in m2m= and as a relation. A relation is "
                "written once: m2m= assigns rows that already exist, a relation spec "
                "writes the rows from the payload and links them. Declaring both writes "
                "it twice and keeps whichever ran last. Assign it or write it, not both."
            )


def extract_relation_data(
    raw: dict[str, Any],
    relations: Mapping[str, RelationSpec],
) -> dict[str, Any]:
    """Pop each relation key out of ``raw`` and return ``{relation: value}``."""
    return {name: raw.pop(name, UNSET) for name in relations}


def relations_in_phase(
    relations: Mapping[str, RelationSpec],
    phase: RelationPhase,
) -> tuple[tuple[str, RelationSpec], ...]:
    """The declared relations belonging to ``phase``, in declaration order."""
    return tuple((name, spec) for name, spec in relations.items() if spec.write_phase is phase)


def post_save_relations(
    relations: Mapping[str, RelationSpec],
) -> tuple[tuple[str, RelationSpec], ...]:
    """Every relation written after the parent's ``save()``, in phase order."""
    return tuple(
        pair for phase in POST_SAVE_PHASES for pair in relations_in_phase(relations, phase)
    )


# --- what a row's write refuses with ---------------------------------------
# Declared here and read by the row writers in ``nested_writes.py``, because
# ``register_row_error`` and ``resolve_m2m`` read them too.

# The two refusals a row's write can carry out of it: the service layer's own,
# and a refusal of the arguments raised deeper in the tree or by a row service
# that validates its row. Both are re-rooted under the row on the way out, and
# neither changes class: which of the two it is says who refused, and a caller
# that catches one by type must still catch it with the row named.
ROW_WRITE_ERRORS = (ServiceValidationError, InvalidArguments)

# What Django raises when a row's own data cannot be written at all: a value
# the field cannot coerce (``ValueError`` or ``TypeError`` from a numeric
# field, ``ValidationError`` from a date, decimal or UUID one), a key the model
# has no field for (``TypeError`` from the constructor), a key that does not
# belong in ``update_fields`` (``ValueError``). None carries a ``detail``, so
# escaping untranslated turns one bad nested row into an unhandled error with
# nothing naming the row. Deliberately **not** extended to caller code -- a
# declared row service, a ``scope`` or an ``m2m`` callable -- because reading its
# ``TypeError`` as a refusal of the arguments would report the caller's own
# bug as the client's mistake; ``_caller_raised`` is how the translation tells
# the two apart at any depth. ``IntegrityError`` is left out on purpose too: a
# constraint is a conflict with rows that exist rather than a shape, and the
# backend's message can quote another row's values.
DJANGO_WRITE_ERRORS = (ValueError, TypeError, ValidationError)

# The helper path translates both kinds.
HELPER_WRITE_ERRORS = (*ROW_WRITE_ERRORS, *DJANGO_WRITE_ERRORS)

# Every class a row write re-roots by the kernel's own rule, which a
# registration may neither narrow nor cover: see ``register_row_error``.
KERNEL_ROW_ERRORS: tuple[type[Exception], ...] = HELPER_WRITE_ERRORS

# A refusal class this package cannot name, mapped to the function reading its
# detail, filled by ``register_row_error``. Process-wide, as the relation specs
# reading it are; a test registering a class of its own restores it after.
ROW_ERROR_READERS: dict[type[Exception], Callable[[Any], Any]] = {}


# Set on an exception raised by caller code the helpers run, as it passes out.
# An attribute rather than a wrapper, because the rule for caller code is that
# it passes through untouched: the caller catches the very exception it raised.
CALLER_RAISED = "_django_service_specs_caller_raised"


def mark_caller_raised(exc: BaseException) -> None:
    """Record that ``exc`` came out of caller code rather than out of Django."""
    setattr(exc, CALLER_RAISED, True)


def resolve_m2m(
    m2m: Mapping[str, Any] | Callable[[Any], Mapping[str, Any]] | None,
    data: Any,
) -> dict[str, Any] | None:
    """A row's ``m2m=`` as a plain ``dict``, or ``None`` when none is declared."""
    if m2m is None:
        return None
    if isinstance(m2m, Mapping):
        return dict(cast("Mapping[str, Any]", m2m))
    derive = cast("Callable[[Any], Mapping[str, Any]]", m2m)
    try:
        return dict(derive(data))
    except DJANGO_WRITE_ERRORS as exc:
        mark_caller_raised(exc)
        raise


def sync_relation_cache(parent: Model, relation: str, row: Any) -> None:
    """Make ``parent``'s cached related object agree with what the write left."""
    if row is None:
        parent._state.fields_cache.pop(relation, None)
        return
    setattr(parent, relation, row)


def sync_collection_cache(parent: Model, change: ChildCollectionChange, spec: RelationSpec) -> None:
    """Drop a prefetched collection this write left inaccurate."""
    if not change:
        return
    updates_wrote_the_cached_rows = (
        isinstance(spec, ChildSpec | GenericRelationSpec) and spec.update_service is None
    )
    membership_changed = bool(change.created or change.deleted or change.unlinked or change.removed)
    if updates_wrote_the_cached_rows and not membership_changed:
        return
    cache: dict[str, Any] | None = getattr(parent, "_prefetched_objects_cache", None)
    if cache is not None:
        cache.pop(change.relation, None)


def handed_on(pool: Mapping[str, Any], call_context: dict[str, Any] | None) -> dict[str, Any]:
    """A mutation helper's pool, as the context it hands its nested row services and scopes."""
    return {**pool, CALL_CONTEXT: {} if call_context is None else call_context}
