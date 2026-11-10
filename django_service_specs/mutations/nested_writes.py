from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from asgiref.sync import sync_to_async
from django.apps import apps
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db.models import Model
from django.utils.translation import gettext

from django_service_specs.mutations.change_result import ChangeResult, ModelT
from django_service_specs.mutations.child_collection_change import ChildCollectionChange
from django_service_specs.mutations.field_change import FieldChange
from django_service_specs.mutations.related_object_change import RelatedObjectChange
from django_service_specs.mutations.utils import (
    CALLER_RAISED,
    DJANGO_WRITE_ERRORS,
    HELPER_WRITE_ERRORS,
    ROW_ERROR_READERS,
    ROW_WRITE_ERRORS,
    aapply_m2m,
    am2m_changes,
    am2m_current_pks,
    apply_m2m,
    assign_changed_values,
    auto_now_field_names,
    changes_for_create,
    coerce_to_dict,
    dimension_field_names,
    extract_relation_data,
    filter_input,
    form_values,
    m2m_changes,
    m2m_current_pks,
    mark_caller_raised,
    post_save_relations,
    reject_m2m_overlap,
    relation_map,
    relations_in_phase,
    resolve_m2m,
    resolve_update_fields,
    split_file_values,
    sync_collection_cache,
    sync_relation_cache,
    write_values,
)
from django_service_specs.parameters.coded_message import CodedMessage
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.non_field_errors import NON_FIELD_ERRORS
from django_service_specs.parameters.utils import coded_messages, key_past_its_column
from django_service_specs.pool.utils import pool_kwargs
from django_service_specs.relations.child_spec import ChildSpec
from django_service_specs.relations.forward_relation_spec import ForwardRelationSpec
from django_service_specs.relations.generic_relation_spec import GenericRelationSpec
from django_service_specs.relations.many_to_many_spec import ManyToManySpec
from django_service_specs.relations.relation_spec import RelationSpec
from django_service_specs.relations.reverse_one_to_one_spec import ReverseOneToOneSpec
from django_service_specs.relations.utils import pk_input_targets
from django_service_specs.services.arun_service import arun_service
from django_service_specs.services.run_service import run_service
from django_service_specs.services.service_validation_error import ServiceValidationError
from django_service_specs.types.is_async import is_async
from django_service_specs.types.relation_orphan import RelationOrphan
from django_service_specs.types.relation_outcome import RelationOutcome
from django_service_specs.types.relation_phase import RelationPhase
from django_service_specs.types.unset import UNSET

# The kinds whose row the parent owns through a link stored on that row. "Child"
# throughout this module means such a row; a generic-relation row differs only in
# that its link is two columns rather than one.
_OwnedRowSpec = ChildSpec | ReverseOneToOneSpec | GenericRelationSpec
# The owned kinds holding *many* rows, so they reconcile a collection and have
# orphans; the reverse one-to-one holds one and has the ``None`` case instead.
_CollectionSpec = ChildSpec | GenericRelationSpec
# The kinds pointing at a row the parent does *not* own, so there is no manager
# to match within and ``scope=`` says which rows this caller may write.
_ScopedSpec = ForwardRelationSpec | ManyToManySpec
# Every kind whose row the mutation helpers write, owned or merely pointed at.
_RowSpec = (
    ChildSpec | ReverseOneToOneSpec | ForwardRelationSpec | ManyToManySpec | GenericRelationSpec
)


def _content_type_for(instance: Model) -> Any:
    """The ``ContentType`` row for ``instance``'s model."""
    if not apps.is_installed("django.contrib.contenttypes"):
        raise ImproperlyConfigured(
            "A generic relation needs 'django.contrib.contenttypes' in INSTALLED_APPS: "
            "the row is linked to its parent by a content type, and without that app "
            "there is no content type to link it to. Add the app, or link the rows with "
            "a plain foreign key and declare the relation as a ChildSpec."
        )
    content_type = apps.get_model("contenttypes", "ContentType")
    return content_type.objects.get_for_model(instance)


def _link_fields(spec: _OwnedRowSpec) -> tuple[str, ...]:
    """The column(s) on the related row holding its link back to the parent."""
    if isinstance(spec, GenericRelationSpec):
        return (spec.content_type_field, spec.object_id_field)
    return (spec.fk,)


def _link_values(spec: _OwnedRowSpec, parent: Model) -> dict[str, Any]:
    """What to assign on a new related row so it points at ``parent``."""
    if isinstance(spec, GenericRelationSpec):
        return {
            spec.content_type_field: _content_type_for(parent),
            spec.object_id_field: parent.pk,
        }
    return {spec.fk: parent}


async def _alink_values(spec: _OwnedRowSpec, parent: Model) -> dict[str, Any]:
    """Async variant of ``_link_values``."""
    if not isinstance(spec, GenericRelationSpec):
        return {spec.fk: parent}
    return {
        spec.content_type_field: await sync_to_async(_content_type_for, thread_sensitive=True)(
            parent
        ),
        spec.object_id_field: parent.pk,
    }


def _fixed_link_fields(spec: _OwnedRowSpec) -> tuple[str, ...]:
    """The link column(s) that cannot hold ``NULL``, so cannot be blanked."""
    return tuple(
        name for name in _link_fields(spec) if not bool(spec.model._meta.get_field(name).null)
    )


def _link_nullable(spec: _OwnedRowSpec) -> bool:
    """Whether the row's link to the parent can be blanked instead of deleted."""
    return not _fixed_link_fields(spec)


def _unlinks_orphans(spec: _OwnedRowSpec, *, relation: str) -> bool:
    """Whether a row this relation lets go is unlinked rather than deleted."""
    if spec.orphan == RelationOrphan.DELETE:
        return False
    if spec.orphan == RelationOrphan.AUTO:
        return _link_nullable(spec)
    fixed: tuple[str, ...] = _fixed_link_fields(spec)
    if fixed:
        columns = ", ".join(f"{spec.model.__name__}.{name}" for name in fixed)
        raise ImproperlyConfigured(
            f"relations[{relation!r}]: orphan={RelationOrphan.UNLINK.value!r} asks for the row "
            f"to be kept and its link blanked, but {columns} cannot hold NULL, so there is no "
            "link to blank. Make the column nullable (null=True, and the migration for it), or "
            f"declare orphan={RelationOrphan.DELETE.value!r} to remove the row — dropping "
            "orphan= altogether deletes it too, by deriving the rule from the column."
        )
    return True


def _collect_removals(
    removals: list[tuple[RelationOutcome, Any]],
) -> dict[str, tuple[Any, ...]]:
    """Bucket ``(status, pk)`` pairs into the change carrier's removal tuples."""
    buckets: dict[RelationOutcome, list[Any]] = {
        RelationOutcome.DELETED: [],
        RelationOutcome.UNLINKED: [],
        RelationOutcome.REMOVED: [],
    }
    for status, pk in removals:
        buckets[status].append(pk)
    return {outcome.value: tuple(pks) for outcome, pks in buckets.items()}


def remove_child(
    child: Model, link: tuple[str, ...], *, unlink: bool
) -> tuple[RelationOutcome, Any]:
    """Detach (``SET_NULL``) or delete (``CASCADE``) ``child``, as ``unlink`` says."""
    pk = child.pk
    if unlink:
        for name in link:
            setattr(child, name, None)
        child.save(update_fields=list(link))
        return (RelationOutcome.UNLINKED, pk)
    child.delete()
    return (RelationOutcome.DELETED, pk)


async def aremove_child(
    child: Model, link: tuple[str, ...], *, unlink: bool
) -> tuple[RelationOutcome, Any]:
    """Async variant of ``remove_child``."""
    pk = child.pk
    if unlink:
        for name in link:
            setattr(child, name, None)
        await child.asave(update_fields=list(link))
        return (RelationOutcome.UNLINKED, pk)
    await child.adelete()
    return (RelationOutcome.DELETED, pk)


def _pk_input_names(model: type[Model], field_map: dict[str, str] | None) -> frozenset[str]:
    """Input keys landing on ``model``'s pk — every spelling, plus ``field_map``."""
    targets: frozenset[str] = pk_input_targets(model)
    mapped: set[str] = {src for src, dest in (field_map or {}).items() if dest in targets}
    return targets | mapped


def _omitted(value: Any) -> bool:
    """Whether a nested row supplied this key at all."""
    return value is None or value is UNSET


def _reject_unmatched_reference(
    item: dict[str, Any],
    spec: _RowSpec,
    path: _RowPath,
) -> None:
    """Refuse a nested row that names a primary key nothing matched."""
    named: dict[str, Any] = {
        key: item[key]
        for key in _pk_input_names(spec.model, spec.field_map)
        if not _omitted(item.get(key))
    }
    if not named:
        return
    raise ServiceValidationError(
        path.namespace(
            [
                f"references {spec.model.__name__} {sorted(named.values())!r}, which this "
                f"write did not match. Saving a new row under a primary key would "
                f"overwrite the row that holds it, so it is refused. Send a row this "
                f"relation may match, or omit the identifier to create a new one."
            ]
        )
    )


def _matched_row_exclude_fields(spec: _RowSpec) -> list[str]:
    """``spec.exclude_fields`` plus every input spelling of the matched row's pk."""
    return [*(spec.exclude_fields or ()), *sorted(_pk_input_names(spec.model, spec.field_map))]


# --- where a row's error lands -------------------------------------------


@dataclass(frozen=True)
class _RowPath:
    """Where one row sits in the incoming arguments, so its error can name it."""

    relation: str
    index: int | None = None

    def namespace(self, detail: Any) -> dict[Any, Any]:
        """Put ``detail`` under the relation name, at this row's position."""
        row: Any = (
            detail
            if isinstance(detail, Mapping)
            else {NON_FIELD_ERRORS: [detail] if isinstance(detail, str) else list(detail)}
        )
        if self.index is None:
            return {self.relation: row}
        return {self.relation: {self.index: row}}


def _row_write_errors() -> tuple[type[Exception], ...]:
    """What a row service's refusal is caught as: the kernel's two and every registered class."""
    return (*ROW_WRITE_ERRORS, *ROW_ERROR_READERS)


def _helper_write_errors() -> tuple[type[Exception], ...]:
    """What the helper path catches: a row service's refusals and Django's write failures."""
    return (*HELPER_WRITE_ERRORS, *ROW_ERROR_READERS)


def _registered_reader(exc: Exception) -> tuple[type[Exception], Callable[[Any], Any]] | None:
    """The registered class ``exc`` was caught as, with its reader, or ``None``."""
    mro = type(exc).__mro__
    caught_as = [(klass, reader) for klass, reader in ROW_ERROR_READERS.items() if klass in mro]
    if not caught_as:
        return None
    return min(caught_as, key=lambda registered: mro.index(registered[0]))


def _caller_raised(exc: BaseException) -> bool:
    """Whether ``exc`` was marked on its way out of caller code."""
    return getattr(exc, CALLER_RAISED, False) is True


def _namespaced_row_error(exc: Exception, path: _RowPath) -> Exception:
    """The same refusal, with the relation (and row) that carried it named."""
    if isinstance(exc, ServiceValidationError):
        return ServiceValidationError(path.namespace(exc.detail))
    if isinstance(exc, InvalidArguments):
        return InvalidArguments(path.namespace(exc.detail))
    if isinstance(exc, ValidationError):
        detail: Any = (
            {field: coded_messages(errors) for field, errors in exc.error_dict.items()}
            if hasattr(exc, "error_dict")
            else coded_messages(exc.error_list)
        )
        return InvalidArguments(path.namespace(detail))
    registered = _registered_reader(exc)
    if registered is not None:
        error_class, read_detail = registered
        return error_class(path.namespace(read_detail(exc)))
    return InvalidArguments(path.namespace([CodedMessage(str(exc), "invalid")]))


# --- per-child service slots ---------------------------------------------


def _child_pool(context: Mapping[str, Any] | None, **seeds: Any) -> dict[str, Any]:
    """Merge the opaque caller ``context`` with the loop's own seeds."""
    return {**(context or {}), **seeds}


def _run_child_service(fn: Callable[..., Any], pool: dict[str, Any]) -> Any:
    """Invoke a per-child service from sync code, opening no savepoint."""
    try:
        return run_service(fn, pool_kwargs(fn, pool), atomic=False)
    except DJANGO_WRITE_ERRORS as exc:
        mark_caller_raised(exc)
        raise


async def _arun_child_service(
    fn: Callable[..., Awaitable[Any]],
    pool: dict[str, Any],
    *,
    relation: str,
    slot: str,
) -> Any:
    """Async variant of ``_run_child_service``, which refuses a slot it cannot await."""
    if not is_async(fn):
        raise ImproperlyConfigured(
            f"relations[{relation!r}]: {slot} is a sync callable, and the async "
            "helpers await every row slot. Declare it with async def, or write "
            "this relation through the sync helpers."
        )
    try:
        return await arun_service(fn, pool_kwargs(fn, pool), atomic=False)
    except DJANGO_WRITE_ERRORS as exc:
        mark_caller_raised(exc)
        raise


def _remove_one_child(
    child: Model,
    spec: _OwnedRowSpec,
    *,
    parent: Model,
    context: Mapping[str, Any] | None,
    unlink: bool,
) -> tuple[RelationOutcome, Any]:
    """Remove one child through ``delete_service`` when declared, else the rule."""
    if spec.delete_service is None:
        return remove_child(child, _link_fields(spec), unlink=unlink)
    pk = child.pk
    _run_child_service(spec.delete_service, _child_pool(context, instance=child, parent=parent))
    return (RelationOutcome.REMOVED, pk)


async def _aremove_one_child(
    child: Model,
    spec: _OwnedRowSpec,
    *,
    relation: str,
    parent: Model,
    context: Mapping[str, Any] | None,
    unlink: bool,
) -> tuple[RelationOutcome, Any]:
    """Async variant of ``_remove_one_child``."""
    if spec.delete_service is None:
        return await aremove_child(child, _link_fields(spec), unlink=unlink)
    pk = child.pk
    await _arun_child_service(
        spec.delete_service,
        _child_pool(context, instance=child, parent=parent),
        relation=relation,
        slot="delete_service",
    )
    return (RelationOutcome.REMOVED, pk)


# --- the forward phase: written before the parent exists ------------------


def apply_forward_relations(
    relation_data: dict[str, Any],
    relations: Mapping[str, RelationSpec],
    *,
    context: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], tuple[RelatedObjectChange, ...]]:
    """Resolve every forward relation and return it as plain field assignments."""
    assignments: dict[str, Any] = {}
    changes: list[RelatedObjectChange] = []
    for relation, spec in relations_in_phase(relations, RelationPhase.FORWARD):
        if not isinstance(spec, ForwardRelationSpec):
            raise _unknown_relation_kind(relation, spec)
        value = relation_data.get(relation, UNSET)
        if value is UNSET:
            changes.append(RelatedObjectChange(relation=relation))
            continue
        target, change = _write_forward_relation(value, spec, relation=relation, context=context)
        assignments[relation] = target
        changes.append(change)
    return (assignments, tuple(changes))


async def aapply_forward_relations(
    relation_data: dict[str, Any],
    relations: Mapping[str, RelationSpec],
    *,
    context: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], tuple[RelatedObjectChange, ...]]:
    """Async variant of ``apply_forward_relations``."""
    assignments: dict[str, Any] = {}
    changes: list[RelatedObjectChange] = []
    for relation, spec in relations_in_phase(relations, RelationPhase.FORWARD):
        if not isinstance(spec, ForwardRelationSpec):
            raise _unknown_relation_kind(relation, spec)
        value = relation_data.get(relation, UNSET)
        if value is UNSET:
            changes.append(RelatedObjectChange(relation=relation))
            continue
        target, change = await _awrite_forward_relation(
            value, spec, relation=relation, context=context
        )
        assignments[relation] = target
        changes.append(change)
    return (assignments, tuple(changes))


def _write_forward_relation(
    value: Any,
    spec: ForwardRelationSpec,
    *,
    relation: str,
    context: Mapping[str, Any] | None,
) -> tuple[Any, RelatedObjectChange]:
    """Write (or clear) one forward relation and return what to assign."""
    if value is None:
        return (None, RelatedObjectChange(relation=relation, outcome=RelationOutcome.CLEARED))
    item = coerce_to_dict(value)
    row_m2m = resolve_m2m(spec.m2m, item)
    path = _RowPath(relation)
    target = _match_scoped_target(item, spec, path=path, context=context)
    if target is None:
        row = _create_row(item, spec, path=path, seeds={}, context=context, m2m=row_m2m)
        return (
            row,
            RelatedObjectChange(relation=relation, outcome=RelationOutcome.CREATED, pk=row.pk),
        )
    row = _update_row(target, item, spec, path=path, seeds={}, context=context, m2m=row_m2m)
    return (row, RelatedObjectChange(relation=relation, outcome=RelationOutcome.UPDATED, pk=row.pk))


async def _awrite_forward_relation(
    value: Any,
    spec: ForwardRelationSpec,
    *,
    relation: str,
    context: Mapping[str, Any] | None,
) -> tuple[Any, RelatedObjectChange]:
    """Async variant of ``_write_forward_relation``."""
    if value is None:
        return (None, RelatedObjectChange(relation=relation, outcome=RelationOutcome.CLEARED))
    item = coerce_to_dict(value)
    row_m2m = resolve_m2m(spec.m2m, item)
    path = _RowPath(relation)
    target = await _amatch_scoped_target(item, spec, path=path, context=context)
    if target is None:
        row = await _acreate_row(item, spec, path=path, seeds={}, context=context, m2m=row_m2m)
        return (
            row,
            RelatedObjectChange(relation=relation, outcome=RelationOutcome.CREATED, pk=row.pk),
        )
    row = await _aupdate_row(target, item, spec, path=path, seeds={}, context=context, m2m=row_m2m)
    return (row, RelatedObjectChange(relation=relation, outcome=RelationOutcome.UPDATED, pk=row.pk))


def _resolve_scope(
    item: dict[str, Any],
    spec: _ScopedSpec,
    *,
    relation: str,
    context: Mapping[str, Any] | None,
) -> tuple[Any, Any] | None:
    """Return ``(queryset, key)`` to match on, or ``None`` for "create it"."""
    key = item.get(spec.match_key)
    if _omitted(key):
        return None
    if spec.scope is None:
        raise ImproperlyConfigured(
            f"relations[{relation!r}]: the incoming row carries a {spec.match_key!r} but the "
            f"spec declares no scope=, which makes it create-only. A {type(spec).__name__} "
            "target is not reached through a manager the parent owns, so matching one by key "
            "unscoped would let any caller write any row of that model by guessing a key. "
            "Declare scope= — a queryset, or a callable resolved from the caller pool — "
            "naming the rows this caller may write."
        )
    scope: Any = spec.scope
    if not callable(scope):
        return (scope, key)
    try:
        queryset: Any = scope(**pool_kwargs(scope, context or {}))
    except DJANGO_WRITE_ERRORS as exc:
        mark_caller_raised(exc)
        raise
    return (queryset, key)


def _scoped_match_miss(
    path: _RowPath,
    spec: _ScopedSpec,
    key: Any,
) -> ServiceValidationError:
    """The error for a match key that names no row this caller may write."""
    return ServiceValidationError(
        path.namespace(
            [
                f"No {spec.model.__name__} with {spec.match_key}={key!r} is available to "
                "write: it does not exist, or it is outside the scope this relation may "
                "write. Omit the key to create a new one."
            ]
        )
    )


def _match_scoped_target(
    item: dict[str, Any],
    spec: _ScopedSpec,
    *,
    path: _RowPath,
    context: Mapping[str, Any] | None,
) -> Any:
    """The in-scope row this payload updates, or ``None`` to create one."""
    resolved = _resolve_scope(item, spec, relation=path.relation, context=context)
    if resolved is None:
        return None
    queryset, key = resolved
    if key_past_its_column(queryset, spec.match_key, key):
        raise _scoped_match_miss(path, spec, key)
    target = queryset.filter(**{spec.match_key: key}).first()
    if target is None:
        raise _scoped_match_miss(path, spec, key)
    return target


async def _amatch_scoped_target(
    item: dict[str, Any],
    spec: _ScopedSpec,
    *,
    path: _RowPath,
    context: Mapping[str, Any] | None,
) -> Any:
    """Async variant of ``_match_scoped_target``."""
    resolved = _resolve_scope(item, spec, relation=path.relation, context=context)
    if resolved is None:
        return None
    queryset, key = resolved
    if key_past_its_column(queryset, spec.match_key, key):
        raise _scoped_match_miss(path, spec, key)
    target = await queryset.filter(**{spec.match_key: key}).afirst()
    if target is None:
        raise _scoped_match_miss(path, spec, key)
    return target


# --- the post-save phases ------------------------------------------------


def apply_relations(
    parent: Model,
    relation_data: dict[str, Any],
    relations: Mapping[str, RelationSpec],
    *,
    created: bool,
    context: Mapping[str, Any] | None = None,
) -> tuple[tuple[ChildCollectionChange, ...], tuple[RelatedObjectChange, ...]]:
    """Write every relation that belongs after the parent's ``save()``."""
    collections: list[ChildCollectionChange] = []
    singular: list[RelatedObjectChange] = []
    for relation, spec in post_save_relations(relations):
        value = relation_data.get(relation, UNSET)
        if isinstance(spec, ReverseOneToOneSpec):
            singular.append(
                _write_reverse_one_to_one(
                    parent, value, spec, relation=relation, created=created, context=context
                )
            )
            continue
        if isinstance(spec, ChildSpec | GenericRelationSpec):
            collection = _write_owned_collection(
                parent, value, spec, relation=relation, created=created, context=context
            )
        elif isinstance(spec, ManyToManySpec):
            collection = _write_m2m_relation(
                parent, value, spec, relation=relation, created=created, context=context
            )
        else:
            raise _unknown_relation_kind(relation, spec)
        collections.append(collection)
        sync_collection_cache(parent, collection, spec)
    return (tuple(collections), tuple(singular))


def _unknown_relation_kind(relation: str, spec: RelationSpec) -> ImproperlyConfigured:
    """The error for a ``RelationSpec`` subclass the library did not define."""
    return ImproperlyConfigured(
        f"relations[{relation!r}]: {type(spec).__name__} is not a relation kind this "
        "library knows how to write or remove. Declare the relation with one of the "
        "spec classes in django_service_specs.relations."
    )


def _write_reverse_one_to_one(
    parent: Model,
    value: Any,
    spec: ReverseOneToOneSpec,
    *,
    relation: str,
    created: bool,
    context: Mapping[str, Any] | None,
) -> RelatedObjectChange:
    """Write the parent's single reverse one-to-one row."""
    if value is UNSET:
        return RelatedObjectChange(relation=relation)
    existing = None if created else spec.model.objects.filter(**{spec.fk: parent}).first()
    if value is None:
        if existing is None:
            return RelatedObjectChange(relation=relation)
        status, pk = _remove_one_child(
            existing,
            spec,
            parent=parent,
            context=context,
            unlink=_unlinks_orphans(spec, relation=relation),
        )
        sync_relation_cache(parent, relation, None)
        return RelatedObjectChange(relation=relation, outcome=status, pk=pk)
    item = coerce_to_dict(value)
    row_m2m = resolve_m2m(spec.m2m, item)
    path = _RowPath(relation)
    if existing is None:
        row = _create_row(
            {**item, **_link_values(spec, parent)},
            spec,
            path=path,
            seeds={"parent": parent},
            context=context,
            m2m=row_m2m,
        )
        outcome = RelationOutcome.CREATED
    else:
        row = _update_row(
            existing, item, spec, path=path, seeds={"parent": parent}, context=context, m2m=row_m2m
        )
        outcome = RelationOutcome.UPDATED
    sync_relation_cache(parent, relation, row)
    return RelatedObjectChange(relation=relation, outcome=outcome, pk=row.pk)


async def _awrite_reverse_one_to_one(
    parent: Model,
    value: Any,
    spec: ReverseOneToOneSpec,
    *,
    relation: str,
    created: bool,
    context: Mapping[str, Any] | None,
) -> RelatedObjectChange:
    """Async variant of ``_write_reverse_one_to_one``."""
    if value is UNSET:
        return RelatedObjectChange(relation=relation)
    existing = None if created else await spec.model.objects.filter(**{spec.fk: parent}).afirst()
    if value is None:
        if existing is None:
            return RelatedObjectChange(relation=relation)
        status, pk = await _aremove_one_child(
            existing,
            spec,
            relation=relation,
            parent=parent,
            context=context,
            unlink=_unlinks_orphans(spec, relation=relation),
        )
        sync_relation_cache(parent, relation, None)
        return RelatedObjectChange(relation=relation, outcome=status, pk=pk)
    item = coerce_to_dict(value)
    row_m2m = resolve_m2m(spec.m2m, item)
    path = _RowPath(relation)
    if existing is None:
        row = await _acreate_row(
            {**item, **await _alink_values(spec, parent)},
            spec,
            path=path,
            seeds={"parent": parent},
            context=context,
            m2m=row_m2m,
        )
        outcome = RelationOutcome.CREATED
    else:
        row = await _aupdate_row(
            existing, item, spec, path=path, seeds={"parent": parent}, context=context, m2m=row_m2m
        )
        outcome = RelationOutcome.UPDATED
    sync_relation_cache(parent, relation, row)
    return RelatedObjectChange(relation=relation, outcome=outcome, pk=row.pk)


def _collection_rows(items: Any, *, relation: str) -> list[dict[str, Any]]:
    """A collection's incoming rows as mappings, refusing a null row before any write."""
    rows = list(items or [])
    nulls = [index for index, row in enumerate(rows) if row is None]
    if nulls:
        message = CodedMessage(gettext("This field cannot be null."), "null")
        raise InvalidArguments({relation: {i: {NON_FIELD_ERRORS: [message]} for i in nulls}})
    return [coerce_to_dict(row) for row in rows]


def _write_owned_collection(
    parent: Model,
    items: Any,
    spec: _CollectionSpec,
    *,
    relation: str,
    created: bool,
    context: Mapping[str, Any] | None,
) -> ChildCollectionChange:
    """Reconcile one owned collection against ``items``."""
    if items is UNSET:
        return ChildCollectionChange(relation=relation)
    existing_by_key: dict[Any, Model] = (
        {} if created else {getattr(e, spec.match_key): e for e in getattr(parent, relation).all()}
    )
    created_pks: list[Any] = []
    updated_pks: list[Any] = []
    matched: set[Any] = set()
    rows = _collection_rows(items, relation=relation)
    for index, item in enumerate(rows):
        child_m2m = resolve_m2m(spec.m2m, item)
        path = _RowPath(relation, index)
        key = item.get(spec.match_key)
        if not _omitted(key) and key in existing_by_key:
            child = _update_row(
                existing_by_key[key],
                item,
                spec,
                path=path,
                seeds={"parent": parent},
                context=context,
                m2m=child_m2m,
            )
            updated_pks.append(child.pk)
            matched.add(key)
        else:
            child = _create_row(
                {**item, **_link_values(spec, parent)},
                spec,
                path=path,
                seeds={"parent": parent},
                context=context,
                m2m=child_m2m,
            )
            created_pks.append(child.pk)
    removals = _remove_orphans(
        existing_by_key, spec, matched, created, relation=relation, parent=parent, context=context
    )
    return ChildCollectionChange(
        relation=relation,
        created=tuple(created_pks),
        updated=tuple(updated_pks),
        **_collect_removals(removals),
    )


def _write_m2m_relation(
    parent: Model,
    items: Any,
    spec: ManyToManySpec,
    *,
    relation: str,
    created: bool,
    context: Mapping[str, Any] | None,
) -> ChildCollectionChange:
    """Write a many-to-many's target rows, then the membership."""
    if items is UNSET:
        return ChildCollectionChange(relation=relation)
    manager: Any = getattr(parent, relation)
    before: list[Any] = [] if created else m2m_current_pks(parent, relation)
    created_pks: list[Any] = []
    updated_pks: list[Any] = []
    targets: list[Any] = []
    rows = _collection_rows(items, relation=relation)
    for index, item in enumerate(rows):
        row_m2m = resolve_m2m(spec.m2m, item)
        path = _RowPath(relation, index)
        match = _match_scoped_target(item, spec, path=path, context=context)
        if match is None:
            row = _create_row(
                item,
                spec,
                path=path,
                seeds={"parent": parent},
                context=context,
                m2m=row_m2m,
            )
            created_pks.append(row.pk)
        else:
            row = _update_row(
                match, item, spec, path=path, seeds={"parent": parent}, context=context, m2m=row_m2m
            )
            updated_pks.append(row.pk)
        targets.append(row)
    if spec.mode == "replace":
        manager.set(targets)
    else:
        manager.add(*targets)
    return ChildCollectionChange(
        relation=relation,
        created=tuple(created_pks),
        updated=tuple(updated_pks),
        unlinked=_m2m_dropped(before, targets, spec),
    )


def _m2m_dropped(
    before: list[Any],
    targets: list[Any],
    spec: ManyToManySpec,
) -> tuple[Any, ...]:
    """The members ``"replace"`` dropped — an unlink, never a delete."""
    if spec.mode != "replace":
        return ()
    kept: set[Any] = {row.pk for row in targets}
    return tuple(pk for pk in before if pk not in kept)


def _create_row(
    data: dict[str, Any],
    spec: _RowSpec,
    *,
    path: _RowPath,
    seeds: dict[str, Any],
    context: Mapping[str, Any] | None,
    m2m: dict[str, Any] | None,
) -> Any:
    """Persist one new related row: ``create_service`` when declared, else the helper."""
    _reject_unmatched_reference(data, spec, path)
    if spec.create_service is not None:
        try:
            return _run_child_service(spec.create_service, _child_pool(context, data=data, **seeds))
        except _row_write_errors() as exc:
            raise _namespaced_row_error(exc, path) from exc
    try:
        return create_instance(
            spec.model,
            data,
            field_map=spec.field_map,
            exclude_fields=spec.exclude_fields,
            m2m=m2m,
            relations=spec.relations,
            context=context,
        ).instance
    except _helper_write_errors() as exc:
        if _caller_raised(exc):
            raise
        raise _namespaced_row_error(exc, path) from exc


async def _acreate_row(
    data: dict[str, Any],
    spec: _RowSpec,
    *,
    path: _RowPath,
    seeds: dict[str, Any],
    context: Mapping[str, Any] | None,
    m2m: dict[str, Any] | None,
) -> Any:
    """Async variant of ``_create_row``."""
    _reject_unmatched_reference(data, spec, path)
    if spec.create_service is not None:
        try:
            return await _arun_child_service(
                spec.create_service,
                _child_pool(context, data=data, **seeds),
                relation=path.relation,
                slot="create_service",
            )
        except _row_write_errors() as exc:
            raise _namespaced_row_error(exc, path) from exc
    try:
        result = await acreate_instance(
            spec.model,
            data,
            field_map=spec.field_map,
            exclude_fields=spec.exclude_fields,
            m2m=m2m,
            relations=spec.relations,
            context=context,
        )
    except _helper_write_errors() as exc:
        if _caller_raised(exc):
            raise
        raise _namespaced_row_error(exc, path) from exc
    return result.instance


def _update_row(
    instance: Model,
    data: dict[str, Any],
    spec: _RowSpec,
    *,
    path: _RowPath,
    seeds: dict[str, Any],
    context: Mapping[str, Any] | None,
    m2m: dict[str, Any] | None,
) -> Any:
    """Persist one matched row through ``update_service`` when declared."""
    if spec.update_service is not None:
        try:
            returned = _run_child_service(
                spec.update_service,
                _child_pool(context, data=data, instance=instance, **seeds),
            )
        except _row_write_errors() as exc:
            raise _namespaced_row_error(exc, path) from exc
        return instance if returned is None else returned
    try:
        update_instance(
            instance,
            data,
            field_map=spec.field_map,
            exclude_fields=_matched_row_exclude_fields(spec),
            m2m=m2m,
            relations=spec.relations,
            context=context,
        )
    except _helper_write_errors() as exc:
        if _caller_raised(exc):
            raise
        raise _namespaced_row_error(exc, path) from exc
    return instance


async def _aupdate_row(
    instance: Model,
    data: dict[str, Any],
    spec: _RowSpec,
    *,
    path: _RowPath,
    seeds: dict[str, Any],
    context: Mapping[str, Any] | None,
    m2m: dict[str, Any] | None,
) -> Any:
    """Async variant of ``_update_row``."""
    if spec.update_service is not None:
        try:
            returned = await _arun_child_service(
                spec.update_service,
                _child_pool(context, data=data, instance=instance, **seeds),
                relation=path.relation,
                slot="update_service",
            )
        except _row_write_errors() as exc:
            raise _namespaced_row_error(exc, path) from exc
        return instance if returned is None else returned
    try:
        await aupdate_instance(
            instance,
            data,
            field_map=spec.field_map,
            exclude_fields=_matched_row_exclude_fields(spec),
            m2m=m2m,
            relations=spec.relations,
            context=context,
        )
    except _helper_write_errors() as exc:
        if _caller_raised(exc):
            raise
        raise _namespaced_row_error(exc, path) from exc
    return instance


def _remove_orphans(
    existing_by_key: dict[Any, Model],
    spec: _CollectionSpec,
    matched: set[Any],
    created: bool,
    *,
    relation: str,
    parent: Model,
    context: Mapping[str, Any] | None,
) -> list[tuple[RelationOutcome, Any]]:
    """Remove pre-update children not matched by the incoming set (replace mode)."""
    removals: list[tuple[RelationOutcome, Any]] = []
    if created or spec.mode != "replace":
        return removals
    unlink = _unlinks_orphans(spec, relation=relation)
    for key, child in existing_by_key.items():
        if key in matched:
            continue
        removals.append(
            _remove_one_child(child, spec, parent=parent, context=context, unlink=unlink)
        )
    return removals


async def aapply_relations(
    parent: Model,
    relation_data: dict[str, Any],
    relations: Mapping[str, RelationSpec],
    *,
    created: bool,
    context: Mapping[str, Any] | None = None,
) -> tuple[tuple[ChildCollectionChange, ...], tuple[RelatedObjectChange, ...]]:
    """Async variant of ``apply_relations`` — same ordering, awaited."""
    collections: list[ChildCollectionChange] = []
    singular: list[RelatedObjectChange] = []
    for relation, spec in post_save_relations(relations):
        value = relation_data.get(relation, UNSET)
        if isinstance(spec, ReverseOneToOneSpec):
            singular.append(
                await _awrite_reverse_one_to_one(
                    parent, value, spec, relation=relation, created=created, context=context
                )
            )
            continue
        if isinstance(spec, ChildSpec | GenericRelationSpec):
            collection = await _awrite_owned_collection(
                parent, value, spec, relation=relation, created=created, context=context
            )
        elif isinstance(spec, ManyToManySpec):
            collection = await _awrite_m2m_relation(
                parent, value, spec, relation=relation, created=created, context=context
            )
        else:
            raise _unknown_relation_kind(relation, spec)
        collections.append(collection)
        sync_collection_cache(parent, collection, spec)
    return (tuple(collections), tuple(singular))


async def _awrite_owned_collection(
    parent: Model,
    items: Any,
    spec: _CollectionSpec,
    *,
    relation: str,
    created: bool,
    context: Mapping[str, Any] | None,
) -> ChildCollectionChange:
    """Async variant of ``_write_owned_collection``."""
    if items is UNSET:
        return ChildCollectionChange(relation=relation)
    existing_by_key: dict[Any, Model] = {}
    if not created:
        existing_by_key = {
            getattr(e, spec.match_key): e async for e in getattr(parent, relation).all()
        }
    created_pks: list[Any] = []
    updated_pks: list[Any] = []
    matched: set[Any] = set()
    rows = _collection_rows(items, relation=relation)
    for index, item in enumerate(rows):
        child_m2m = resolve_m2m(spec.m2m, item)
        path = _RowPath(relation, index)
        key = item.get(spec.match_key)
        if not _omitted(key) and key in existing_by_key:
            child = await _aupdate_row(
                existing_by_key[key],
                item,
                spec,
                path=path,
                seeds={"parent": parent},
                context=context,
                m2m=child_m2m,
            )
            updated_pks.append(child.pk)
            matched.add(key)
        else:
            child = await _acreate_row(
                {**item, **await _alink_values(spec, parent)},
                spec,
                path=path,
                seeds={"parent": parent},
                context=context,
                m2m=child_m2m,
            )
            created_pks.append(child.pk)
    removals = await _aremove_orphans(
        existing_by_key, spec, matched, created, relation=relation, parent=parent, context=context
    )
    return ChildCollectionChange(
        relation=relation,
        created=tuple(created_pks),
        updated=tuple(updated_pks),
        **_collect_removals(removals),
    )


async def _awrite_m2m_relation(
    parent: Model,
    items: Any,
    spec: ManyToManySpec,
    *,
    relation: str,
    created: bool,
    context: Mapping[str, Any] | None,
) -> ChildCollectionChange:
    """Async variant of ``_write_m2m_relation``."""
    if items is UNSET:
        return ChildCollectionChange(relation=relation)
    manager: Any = getattr(parent, relation)
    before: list[Any] = [] if created else await am2m_current_pks(parent, relation)
    created_pks: list[Any] = []
    updated_pks: list[Any] = []
    targets: list[Any] = []
    rows = _collection_rows(items, relation=relation)
    for index, item in enumerate(rows):
        row_m2m = resolve_m2m(spec.m2m, item)
        path = _RowPath(relation, index)
        match = await _amatch_scoped_target(item, spec, path=path, context=context)
        if match is None:
            row = await _acreate_row(
                item,
                spec,
                path=path,
                seeds={"parent": parent},
                context=context,
                m2m=row_m2m,
            )
            created_pks.append(row.pk)
        else:
            row = await _aupdate_row(
                match, item, spec, path=path, seeds={"parent": parent}, context=context, m2m=row_m2m
            )
            updated_pks.append(row.pk)
        targets.append(row)
    if spec.mode == "replace":
        await manager.aset(targets)
    else:
        await manager.aadd(*targets)
    return ChildCollectionChange(
        relation=relation,
        created=tuple(created_pks),
        updated=tuple(updated_pks),
        unlinked=_m2m_dropped(before, targets, spec),
    )


async def _aremove_orphans(
    existing_by_key: dict[Any, Model],
    spec: _CollectionSpec,
    matched: set[Any],
    created: bool,
    *,
    relation: str,
    parent: Model,
    context: Mapping[str, Any] | None,
) -> list[tuple[RelationOutcome, Any]]:
    """Async variant of ``_remove_orphans``."""
    removals: list[tuple[RelationOutcome, Any]] = []
    if created or spec.mode != "replace":
        return removals
    unlink = _unlinks_orphans(spec, relation=relation)
    for key, child in existing_by_key.items():
        if key in matched:
            continue
        removals.append(
            await _aremove_one_child(
                child, spec, relation=relation, parent=parent, context=context, unlink=unlink
            )
        )
    return removals


def cascade_owned(
    parent: Model,
    relations: Mapping[str, RelationSpec],
    *,
    context: Mapping[str, Any] | None = None,
) -> tuple[tuple[ChildCollectionChange, ...], tuple[RelatedObjectChange, ...]]:
    """Remove what ``parent`` owns, deepest first, before ``parent`` itself goes."""
    collections: list[ChildCollectionChange] = []
    singular: list[RelatedObjectChange] = []
    for relation, spec in relations.items():
        if isinstance(spec, ReverseOneToOneSpec):
            removal = _delete_owned_row(parent, spec, relation=relation, context=context)
            if removal:
                sync_relation_cache(parent, relation, None)
            singular.append(removal)
            continue
        if isinstance(spec, ForwardRelationSpec):
            singular.append(RelatedObjectChange(relation=relation))
            continue
        if isinstance(spec, ChildSpec | GenericRelationSpec):
            collection = _delete_owned_collection(parent, spec, relation=relation, context=context)
        elif isinstance(spec, ManyToManySpec):
            collection = _clear_m2m_membership(parent, relation=relation)
        else:
            raise _unknown_relation_kind(relation, spec)
        collections.append(collection)
        sync_collection_cache(parent, collection, spec)
    return (tuple(collections), tuple(singular))


async def acascade_owned(
    parent: Model,
    relations: Mapping[str, RelationSpec],
    *,
    context: Mapping[str, Any] | None = None,
) -> tuple[tuple[ChildCollectionChange, ...], tuple[RelatedObjectChange, ...]]:
    """Async variant of ``cascade_owned`` — same rule, awaited."""
    collections: list[ChildCollectionChange] = []
    singular: list[RelatedObjectChange] = []
    for relation, spec in relations.items():
        if isinstance(spec, ReverseOneToOneSpec):
            removal = await _adelete_owned_row(parent, spec, relation=relation, context=context)
            if removal:
                sync_relation_cache(parent, relation, None)
            singular.append(removal)
            continue
        if isinstance(spec, ForwardRelationSpec):
            singular.append(RelatedObjectChange(relation=relation))
            continue
        if isinstance(spec, ChildSpec | GenericRelationSpec):
            collection = await _adelete_owned_collection(
                parent, spec, relation=relation, context=context
            )
        elif isinstance(spec, ManyToManySpec):
            collection = await _aclear_m2m_membership(parent, relation=relation)
        else:
            raise _unknown_relation_kind(relation, spec)
        collections.append(collection)
        sync_collection_cache(parent, collection, spec)
    return (tuple(collections), tuple(singular))


def _delete_owned_collection(
    parent: Model,
    spec: _CollectionSpec,
    *,
    relation: str,
    context: Mapping[str, Any] | None,
) -> ChildCollectionChange:
    """Remove every row of one owned collection, its own relations first."""
    unlink = _unlinks_orphans(spec, relation=relation)
    nested = relation_map(spec.relations)
    removals: list[tuple[RelationOutcome, Any]] = []
    for child in getattr(parent, relation).all():
        cascade_owned(child, nested, context=context)
        removals.append(
            _remove_one_child(child, spec, parent=parent, context=context, unlink=unlink)
        )
    return ChildCollectionChange(relation=relation, **_collect_removals(removals))


async def _adelete_owned_collection(
    parent: Model,
    spec: _CollectionSpec,
    *,
    relation: str,
    context: Mapping[str, Any] | None,
) -> ChildCollectionChange:
    """Async variant of ``_delete_owned_collection``."""
    unlink = _unlinks_orphans(spec, relation=relation)
    nested = relation_map(spec.relations)
    removals: list[tuple[RelationOutcome, Any]] = []
    async for child in getattr(parent, relation).all():
        await acascade_owned(child, nested, context=context)
        removals.append(
            await _aremove_one_child(
                child, spec, relation=relation, parent=parent, context=context, unlink=unlink
            )
        )
    return ChildCollectionChange(relation=relation, **_collect_removals(removals))


def _delete_owned_row(
    parent: Model,
    spec: ReverseOneToOneSpec,
    *,
    relation: str,
    context: Mapping[str, Any] | None,
) -> RelatedObjectChange:
    """Remove the parent's single reverse one-to-one row, if it has one."""
    row = spec.model.objects.filter(**{spec.fk: parent}).first()
    if row is None:
        return RelatedObjectChange(relation=relation)
    cascade_owned(row, relation_map(spec.relations), context=context)
    status, pk = _remove_one_child(
        row, spec, parent=parent, context=context, unlink=_unlinks_orphans(spec, relation=relation)
    )
    return RelatedObjectChange(relation=relation, outcome=status, pk=pk)


async def _adelete_owned_row(
    parent: Model,
    spec: ReverseOneToOneSpec,
    *,
    relation: str,
    context: Mapping[str, Any] | None,
) -> RelatedObjectChange:
    """Async variant of ``_delete_owned_row``."""
    row = await spec.model.objects.filter(**{spec.fk: parent}).afirst()
    if row is None:
        return RelatedObjectChange(relation=relation)
    await acascade_owned(row, relation_map(spec.relations), context=context)
    status, pk = await _aremove_one_child(
        row,
        spec,
        relation=relation,
        parent=parent,
        context=context,
        unlink=_unlinks_orphans(spec, relation=relation),
    )
    return RelatedObjectChange(relation=relation, outcome=status, pk=pk)


def _clear_m2m_membership(parent: Model, *, relation: str) -> ChildCollectionChange:
    """Drop every member of one many-to-many, deleting no target row."""
    manager: Any = getattr(parent, relation)
    members: tuple[Any, ...] = tuple(m2m_current_pks(parent, relation))
    manager.clear()
    return ChildCollectionChange(relation=relation, unlinked=members)


async def _aclear_m2m_membership(parent: Model, *, relation: str) -> ChildCollectionChange:
    """Async variant of ``_clear_m2m_membership``."""
    manager: Any = getattr(parent, relation)
    members: tuple[Any, ...] = tuple(await am2m_current_pks(parent, relation))
    await manager.aclear()
    return ChildCollectionChange(relation=relation, unlinked=members)


# --- the entry points' bodies ----------------------------------------------


def _read_input(
    data: Any,
    *,
    field_map: dict[str, str] | None,
    exclude_fields: list[str] | None,
    m2m: dict[str, Any] | None,
    relations: Mapping[str, RelationSpec] | None,
) -> tuple[dict[str, RelationSpec], dict[str, Any], dict[str, Any]]:
    """A write's input as its relation specs, each relation's payload, and the row's own values."""
    relation_specs = relation_map(relations)
    reject_m2m_overlap(m2m, relation_specs)
    raw: dict[str, Any] = coerce_to_dict(data)
    relation_data: dict[str, Any] = extract_relation_data(raw, relation_specs)
    new_values = filter_input(raw, field_map=field_map, exclude_fields=exclude_fields)
    return (relation_specs, relation_data, new_values)


def _build_instance(model: type[ModelT], values: dict[str, Any]) -> ModelT:
    """An unsaved ``model`` row, built as ``construct_instance`` builds a ModelForm's."""
    plain_values, file_values = split_file_values(model, values)
    instance: ModelT = model(**plain_values)
    write_values(instance, file_values)
    return instance


def _save_fields(
    instance: Model, field_changes: tuple[FieldChange, ...], update_fields: bool | list[str]
) -> list[str] | None:
    """The ``update_fields`` an update's ``save()`` is called with, ``None`` for the whole row."""
    changed: tuple[str, ...] = tuple(change.field for change in field_changes)
    return resolve_update_fields(
        update_fields,
        changed,
        auto_now_field_names(instance) + dimension_field_names(instance, changed),
    )


def create_instance(
    model: type[ModelT],
    data: Any,
    *,
    field_map: dict[str, str] | None = None,
    exclude_fields: list[str] | None = None,
    m2m: dict[str, Any] | None = None,
    relations: Mapping[str, RelationSpec] | None = None,
    context: Mapping[str, Any] | None = None,
) -> ChangeResult[ModelT]:
    """The body of ``create_from_input``."""
    relation_specs, relation_data, new_values = _read_input(
        data, field_map=field_map, exclude_fields=exclude_fields, m2m=m2m, relations=relations
    )
    forward_values, forward_changes = apply_forward_relations(
        relation_data, relation_specs, context=context
    )
    new_values.update(forward_values)
    new_values = form_values(model, new_values)
    instance = _build_instance(model, new_values)
    instance.save()
    field_changes = changes_for_create(new_values)
    m2m_field_changes, to_apply = m2m_changes(instance, m2m, created=True)
    apply_m2m(instance, to_apply)
    child_changes, related_changes = apply_relations(
        instance, relation_data, relation_specs, created=True, context=context
    )
    return ChangeResult(
        instance=instance,
        created=True,
        changes=field_changes + m2m_field_changes,
        children=child_changes,
        relations=forward_changes + related_changes,
    )


def update_instance(
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
    """The body of ``update_from_input``."""
    relation_specs, relation_data, new_values = _read_input(
        data, field_map=field_map, exclude_fields=exclude_fields, m2m=m2m, relations=relations
    )
    forward_values, forward_changes = apply_forward_relations(
        relation_data, relation_specs, context=context
    )
    new_values.update(forward_values)
    field_changes = assign_changed_values(instance, new_values)
    for relation, target in forward_values.items():
        sync_relation_cache(instance, relation, target)
    m2m_field_changes, to_apply = m2m_changes(instance, m2m, created=False)
    save_fields = _save_fields(instance, field_changes, update_fields)
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


async def acreate_instance(
    model: type[ModelT],
    data: Any,
    *,
    field_map: dict[str, str] | None = None,
    exclude_fields: list[str] | None = None,
    m2m: dict[str, Any] | None = None,
    relations: Mapping[str, RelationSpec] | None = None,
    context: Mapping[str, Any] | None = None,
) -> ChangeResult[ModelT]:
    """The body of ``acreate_from_input``."""
    relation_specs, relation_data, new_values = _read_input(
        data, field_map=field_map, exclude_fields=exclude_fields, m2m=m2m, relations=relations
    )
    forward_values, forward_changes = await aapply_forward_relations(
        relation_data, relation_specs, context=context
    )
    new_values.update(forward_values)
    new_values = form_values(model, new_values)
    instance = _build_instance(model, new_values)
    await instance.asave()
    field_changes = changes_for_create(new_values)
    m2m_field_changes, to_apply = await am2m_changes(instance, m2m, created=True)
    await aapply_m2m(instance, to_apply)
    child_changes, related_changes = await aapply_relations(
        instance, relation_data, relation_specs, created=True, context=context
    )
    return ChangeResult(
        instance=instance,
        created=True,
        changes=field_changes + m2m_field_changes,
        children=child_changes,
        relations=forward_changes + related_changes,
    )


async def aupdate_instance(
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
    """The body of ``aupdate_from_input``."""
    relation_specs, relation_data, new_values = _read_input(
        data, field_map=field_map, exclude_fields=exclude_fields, m2m=m2m, relations=relations
    )
    forward_values, forward_changes = await aapply_forward_relations(
        relation_data, relation_specs, context=context
    )
    new_values.update(forward_values)
    field_changes = assign_changed_values(instance, new_values)
    for relation, target in forward_values.items():
        sync_relation_cache(instance, relation, target)
    m2m_field_changes, to_apply = await am2m_changes(instance, m2m, created=False)
    save_fields = _save_fields(instance, field_changes, update_fields)
    if field_changes or update_fields is False:
        if save_fields is None:
            await instance.asave()
        else:
            await instance.asave(update_fields=save_fields)
    await aapply_m2m(instance, to_apply)
    child_changes, related_changes = await aapply_relations(
        instance, relation_data, relation_specs, created=False, context=context
    )
    return ChangeResult(
        instance=instance,
        created=False,
        changes=field_changes + m2m_field_changes,
        children=child_changes,
        relations=forward_changes + related_changes,
    )
