"""Internal helpers shared across the ``relations`` package.

``pk_input_targets``, ``integer_column_range``, ``integer_range_refusal``
and ``key_past_its_column`` are the exceptions to the package name. The
write path in ``mutations`` shares the first, so the three spellings of a
primary key are written down once rather than agreed between two modules.
The others are shared by every place a number a caller sent reaches an
integer column - a relation write's scoped match, the forms adapter's model
choice field and ``ModelForm`` integer column, ``resolve_principal``, and
the selector applying a FilterSet's filters - so each is held to one reading
of the column's range, and refused past it in one set of words.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import connections
from django.db.models import ForeignKey, IntegerField, Model

from django_service_specs.relations.relation_mode import RelationMode
from django_service_specs.relations.relation_orphan import RelationOrphan

VALID_RELATION_MODES = tuple(mode.value for mode in RelationMode)


def validate_relation_mode(mode: str, *, label: str) -> None:
    """Reject a ``mode`` that is neither ``"replace"`` nor ``"merge"``.

    Shared by every relation kind that reconciles a collection so the two words
    mean the same thing on all of them.
    """
    if mode not in VALID_RELATION_MODES:
        raise ValueError(f"{label}.mode must be one of {VALID_RELATION_MODES}; got {mode!r}.")


VALID_RELATION_ORPHANS = tuple(orphan.value for orphan in RelationOrphan)


def validate_relation_orphan(orphan: str, *, delete_service: Any, label: str) -> None:
    """Check ``orphan``, and refuse it beside the service that would silence it.

    A ``delete_service`` replaces the unlink-or-delete rule outright, so an
    explicit ``orphan`` beside one would decide nothing and be silently ignored.
    ``AUTO`` is exempt because it states nothing — it is the default, carried by
    every spec that does not mention ``orphan`` at all.
    """
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


def validate_relation_services(
    *,
    label: str,
    services: Mapping[str, Any],
    shaping: Mapping[str, Any],
) -> None:
    """Refuse a relation spec that declares a row service *and* row shaping.

    A ``create_service`` / ``update_service`` stands in for the mutation-helper
    call, so every knob configuring that call is bypassed for the row — silently,
    unless caught here.

    Callers must keep reconciliation fields (``fk`` / ``match_key`` / ``mode`` /
    ``scope`` / orphan handling) out of both mappings, and must not pass
    ``delete_service`` in ``services``: it replaces the unlink-or-delete rule
    rather than the helper call, so it composes with row shaping.
    """
    declared_services: list[str] = sorted(name for name, value in services.items() if value)
    if not declared_services:
        return
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
    """The names an incoming row can use to mean ``model``'s primary key.

    Three spellings reach the same column and a payload may send any of them:
    ``pk``, the field's ``name``, and its ``attname`` (``id``/``id`` for an
    implicit key, ``author``/``author_id`` where a one-to-one *is* the key).
    """
    return frozenset({"pk", model._meta.pk.name, model._meta.pk.attname})


WIDEST_INTEGER = (-(2**63), 2**63 - 1)
"""A signed 64-bit integer's range: the widest integer column any backend has,
and the most SQLite's driver hands on."""


def integer_column_range(field: Any, using: str) -> tuple[int, int] | None:
    """The integers ``field``'s column holds on the database ``using``, or ``None``.

    ``None`` for anything but an integer column, a key on which no integer
    can be too large: a text column holds any integer's digits. The range is
    the database's own, as Django reads it to answer an exact lookup past it
    with no rows and, from 5.0, to validate a model's integer field. Django
    4.2 states none for SQLite, whose driver still refuses a value past 64
    bits, and raises ``OverflowError`` for one; from 5.0 it states exactly
    that one. No backend's integer column is wider, so it is the range where
    none is stated.
    """
    if not isinstance(field, IntegerField):
        return None
    low, high = connections[using].ops.integer_field_range(field.get_internal_type())
    return (
        WIDEST_INTEGER[0] if low is None else low,
        WIDEST_INTEGER[1] if high is None else high,
    )


def integer_range_refusal(number: int, bounds: tuple[int, int]) -> ValidationError | None:
    """The refusal of ``number`` past ``bounds``, an integer column's range, or ``None`` inside it.

    In the words, and with the code, of the validator Django's model integer
    field carries from 5.0, where the backend states the column's range:
    ``min_value`` past its bottom, ``max_value`` past its top. Both ends are
    inclusive, as the column's are.
    """
    low, high = bounds
    try:
        MinValueValidator(low)(number)
        MaxValueValidator(high)(number)
    except ValidationError as error:
        return error
    return None


def key_past_its_column(queryset: Any, name: str, key: Any) -> bool:
    """Whether ``key`` is past the range of the integer column ``name`` names on ``queryset``'s model.

    Such a key names no row. Django answers an exact lookup with it with no
    rows where the backend states the range, from 5.0; where it states none,
    as Django 4.2's SQLite backend does, the lookup hands the key to the
    driver, which raises ``OverflowError``. So a caller asks this first and
    reads ``True`` as its own "no such row". ``name`` is a column's name or
    attname, or ``pk``; a name that is no column of the model, such as a
    lookup path, is ``False``, the lookup's alone. The key is read as the
    column's own lookup reads it, so a string of digits is the integer it
    spells, and a string that spells no number raises the ``ValueError`` the
    lookup would, in Django's words
    (test_a_key_that_spells_no_number_raises_as_the_lookup_did). A key of
    a type the column cannot read as a number, such as a row, is ``False``,
    the lookup's. A foreign key's column holds the key of the row it points
    at, so its range is that key's
    (test_a_key_on_a_foreign_key_is_held_to_the_column_it_points_at).
    """
    opts = queryset.model._meta
    columns: dict[str, Any] = {
        **{column.attname: column for column in opts.concrete_fields},
        **{column.name: column for column in opts.concrete_fields},
        "pk": opts.pk,
    }
    column: Any = columns.get(name)
    while isinstance(column, ForeignKey):
        column = column.target_field
    bounds = integer_column_range(column, queryset.db)
    # test_an_integer_on_a_text_column_is_matched_as_its_digits fails without
    # this: a text column holds any integer's digits.
    if bounds is None:
        return False
    try:
        number = column.get_prep_value(key)
    except TypeError:
        # A key that is no number at all, such as the row a foreign key
        # points at, which the lookup reads as the row's own key: the
        # lookup's (test_a_row_sent_for_a_foreign_key_is_matched_as_its_key).
        return False
    low, high = bounds
    return not low <= number <= high


def validate_pk_field_map(
    *,
    label: str,
    model: type[Model],
    match_key: str,
    field_map: Mapping[str, str] | None,
) -> None:
    """Refuse a ``field_map`` that renames an input key onto the primary key,
    on a spec that also matches *by* the primary key.

    The two readers of a nested row disagree about ``field_map``, and where the
    match key is the primary key that disagreement leaves no working payload.
    Matching reads the row exactly as it arrived (``item[match_key]``), so a
    payload spelling its key ``ident`` never matches; the primary-key guard
    *does* fold ``field_map`` in, sees ``ident``, reads it as a key nothing
    matched, and refuses the row. Every payload using the mapped name is
    rejected, and none can ever match.

    Scoped to a primary-key ``match_key`` because that is the whole of what is
    unreachable. Mapped onto a *natural* match key the same declaration is
    coherent -- the row matches on its natural key and the alias goes on
    guarding creates, exactly as a plainly-spelled ``pk`` would.

    Refused rather than resolved: ``match_key`` names an input key on one side
    and a model field on the other, so "apply ``field_map`` to it too" has no
    single correct answer, and a spec no payload can reach is better caught
    where it is written than on the first request that tries.
    """
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
