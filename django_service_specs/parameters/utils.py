"""The spellings every refusal of arguments shares, and the readings behind them.

[`InvalidArguments`][django_service_specs.parameters.invalid_arguments.InvalidArguments]
documents the tree these go into. They live here so that everything producing
one - the shape check, ``coerce_flat``, a relation write re-rooting a row's
refusal, an adapter's Validator - spells them the same way, rather than each
its own and a transport learning several. The one reading of an
unknown-arguments policy sits here too, shared by the shape check and its
schema.

So do the checks of a number a caller sent against the integer column it
reaches. They are shared by every place such a number meets a column - a
relation write's scoped match, the forms adapter's model choice field and
``ModelForm`` integer column, ``clean_held_to_their_columns`` validating a
project's own form with the same guards, ``resolve_principal``, and the
selector applying a FilterSet's filters - so each reads a lookup's path to
its column one way (``path_column``), and refuses a number in one set of
words. A key is held to the range its column states
(``integer_column_range``), since past it no row holds the key on any
version; a filter's value, which a comparison reads, is held to
``WIDEST_INTEGER``, what any driver binds. They are here rather than with
the relations, which read them too, because dispatch reaches them through
principal resolution and the selector, and dispatch imports no model write."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Any

from django import forms
from django.core.exceptions import FieldDoesNotExist, FieldError, ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import connections
from django.db.models import ForeignObjectRel, IntegerField, Model
from django.db.models.constants import LOOKUP_SEP
from django.db.models.fields.related import RelatedField
from django.utils.translation import gettext

from django_service_specs.parameters.coded_message import CodedMessage
from django_service_specs.parameters.max_length_in_force import max_length_in_force
from django_service_specs.parameters.parameters import Parameter
from django_service_specs.types.unknown_arguments import UnknownArguments


def coded_messages(errors: Iterable[ValidationError]) -> list[CodedMessage]:
    """Every message Django's ``errors`` carry, in Django's words and with Django's code.

    For a step that hands on a ``ValidationError`` Django or a library over it
    raised - a form's errors, a FilterSet's, a model's uniqueness checks, a
    dataclass's ``__post_init__`` - where reading each message as a ``str``
    would drop its code. Rendered exactly as iterating the error renders it,
    ``message % params`` where there are params, so the words are unchanged.
    One raised with no code says ``"invalid"``, as DRF's ``get_error_detail``
    defaults one. An error built from a dict is read field by field, in its
    own order, as its ``messages`` flattens it.

    Django's codes are Django's, which are not always DRF's: a ``unique_together``
    collision says ``"unique_together"`` where a DRF serializer's validator
    says ``"unique"``.
    """
    return [
        CodedMessage(_rendered(leaf), leaf.code or "invalid")
        for error in errors
        for leaf in _leaves(error)
    ]


def _leaves(error: ValidationError) -> list[ValidationError]:
    """The one-message errors ``error`` holds: its list, or each field's list in turn."""
    if hasattr(error, "error_dict"):
        # test_a_post_init_refusal_keeps_django_s_code_or_says_invalid[by-field]
        # fails without this: a dict-built error has no ``error_list``.
        return [leaf for field in error.error_dict.values() for leaf in field]
    return error.error_list


def _rendered(leaf: ValidationError) -> str:
    """A one-message error's words, as ``ValidationError.__iter__`` renders them."""
    message = leaf.message
    if leaf.params:
        message %= leaf.params
    return str(message)


def length_problem(param: Parameter, count: int) -> CodedMessage | None:
    """The refusal of an array of ``count`` elements, or ``None`` where ``param`` takes that many.

    In DRF's words, its ``ListField`` and ``ListSerializer`` both: no Django
    catalog entry counts a list's elements (``MaxLengthValidator`` counts a
    string's characters), and DRF's catalog translates these wherever DRF is
    installed, which is where a djangorestframework-services caller already
    reads them, and with DRF's codes, ``"max_length"`` and ``"min_length"``.
    """
    most = max_length_in_force(param)
    if most is not None and count > most:
        return CodedMessage(
            gettext("Ensure this field has no more than {max_length} elements.").format(
                max_length=most
            ),
            "max_length",
        )
    if param.min_length is not None and count < param.min_length:
        return CodedMessage(
            gettext("Ensure this field has at least {min_length} elements.").format(
                min_length=param.min_length
            ),
            "min_length",
        )
    return None


_INTEGRAL_DECIMAL = re.compile(r"\.0*\s*$")
"""A decimal point with nothing after it but zeros and space, stripped before ``int``.

It is Django's own expression: ``forms.IntegerField`` strips exactly this, and
DRF's ``IntegerField`` does too, so ``"5.0"`` and ``"5."`` are 5 to both while
``"5.5"`` is still refused. A reading stricter than the fields behind it would
refuse a value the worker reads as a whole number."""


def parse_number(json_type: str, text: str) -> int | float | None:
    """The number ``text`` spells for an ``integer`` or a ``number``, or ``None`` if it spells none.

    The one reading of a numeric string, shared by ``coerce_flat``, which reads
    every flat transport's strings, and the shape check, which reads a string
    a JSON caller sent for a number. One function, so the two accept exactly
    the same strings and a query string and a JSON body carrying the same
    ``"3"`` reach the Validator as the same 3.

    An integer is read as Django's ``IntegerField`` reads one: ``"5.0"``,
    ``"5."``, ``"5 .0"`` and ``" 5 "`` are 5, and ``"5.5"`` and ``"1e3"`` are
    no integer. That is looser than pydantic's lax ``int``, which refuses
    ``"5."`` and ``"5 .0"``. A number is any string Python's ``float`` reads,
    as Django's ``FloatField`` reads it, so ``"1e3"`` and ``"5."`` are numbers,
    as pydantic reads them too, and ``"5 .0"`` is none. NaN and the infinities
    parse and are no number, since no JSON caller can send one.

    **A number spelling an integer is that exact** ``int``, and a ``float``
    only where a point or an exponent is spelled: what a JSON decoder makes
    of the same literal, so ``"3"`` reaches the Validator as the JSON ``3``
    does. Through ``float`` alone, every integer past 2**53 was rounded to a
    neighbour, and a key sent for a ``number`` named the neighbour's row
    (test_a_number_spelling_an_integer_is_that_exact_int). The ``float``
    reading still decides what is a number. Digits alone that ``int`` refuses
    - past the 4300 digits it reads from Python 3.10.7 on, which zeros in
    front can reach while ``float`` still reads a finite value - spell no
    number, rather than a ``float`` neighbour, as they spell no integer; a
    Python with no limit reads them exactly. A fraction past a ``float``'s
    precision is rounded, as a JSON decoder rounds it: a value that must be
    exact is a ``decimal``.

    **Only an ASCII string spells one.** Python's ``int`` and ``float``,
    and so Django's fields, read Arabic-Indic and fullwidth digits and strip
    any Unicode space, which no JSON number is spelled with and pydantic
    refuses; reading them would hand on a number the caller never wrote in
    digits. Stricter than Django's forms there, and only there. A decimal
    string is not read here: the shape check reads it as ``Decimal`` does,
    which takes those digits.

    The caller decides what a ``None`` means: a flat transport refuses it, and
    the shape check refuses the string as the type it is not.
    """
    if not text.isascii():
        # test_a_number_spelled_outside_ascii_spells_none fails without this.
        return None
    if json_type == "integer":
        try:
            return int(_INTEGRAL_DECIMAL.sub("", text))
        except ValueError:
            return None
    try:
        number = float(text)
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    try:
        # test_a_number_spelling_an_integer_is_that_exact_int fails without this.
        return int(text)
    except ValueError:
        # Spelled with neither a point nor an exponent, the digits are an
        # integer, and one ``int`` refuses is past its digit limit: no number
        # at all, never the neighbour ``float`` rounds it to
        # (test_an_integer_literal_past_int_s_digit_limit_is_refused_never_rounded).
        return number if any(mark in text for mark in ".eE") else None


def unknown_arguments_policy(value: UnknownArguments | str) -> UnknownArguments:
    """``value`` as a policy: a member, or its plain value, refusing what is not a policy.

    Normalized, so the policy's plain value works and a misspelt one raises
    ``ValueError`` rather than quietly falling through to one policy or the
    other. ``PASSTHROUGH`` is a valid member and not a policy, so it is
    refused here too: both readers test only ``is REJECT`` after this, and a
    member let through would run as ``IGNORE`` with nothing failing.
    """
    policy = UnknownArguments(value)
    if policy is UnknownArguments.PASSTHROUGH:
        raise ValueError(
            "UnknownArguments.PASSTHROUGH is refused: it is kept as a name and is not a "
            "policy, since an argument no parameter declares never reaches a callable. "
            "Pass REJECT, or IGNORE to drop the undeclared argument."
        )
    return policy


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


def path_column(model: type[Model], path: str) -> Any:
    """The column a lookup path on ``model`` compares a value with, or ``None`` where it names none.

    Each part of the path is a field of the model the part before it relates
    to, and ``pk`` is the model's key, as Django reads a lookup's path; a
    field's attname, ``owner_id``, names it too. A relation compares the key
    of the row it reaches, so the column is that key's, whichever way the
    relation runs: a foreign key's own column holds the other row's key, and
    a many-to-many or a reverse foreign key matches the related row's. A
    multi-table child's key is the link to its parent, and so the parent's
    key. ``None`` past a field that relates to nothing, which is a transform
    such as ``year``
    (test_a_transform_on_the_filter_s_path_is_left_to_the_lookup), for a
    name no model declares, such as an annotation
    (test_a_filter_on_an_annotation_is_left_to_the_database), and for a
    relation over more than one column, a ``ForeignObject`` naming several,
    which compares no one column with a value
    (test_a_relation_over_several_columns_leaves_a_call_sending_nothing_alone).

    One arc to coverage, a kind each: ``owner_key`` in
    test_it_is_refused_at_the_argument_that_sent_it (a forward relation) and
    TestAKeyReachedThroughAnyRelation's ``reverse`` (a reverse one), both in
    ``tests/selectors/test_shape_queryset.py``.
    """
    opts: Any = model._meta
    column: Any = None
    for part in path.split(LOOKUP_SEP):
        if opts is None:
            return None
        try:
            column = opts.pk if part == "pk" else opts.get_field(part)
        except FieldDoesNotExist:
            return None
        related = column.related_model
        opts = None if related is None else related._meta
    while isinstance(column, RelatedField | ForeignObjectRel):
        try:
            column = column.target_field
        except FieldError:
            # Django's refusal to name one target for a relation over several
            # columns, either way it runs.
            return None
    return column


def key_past_its_column(queryset: Any, name: str, key: Any) -> bool:
    """Whether ``key`` is past the range of the integer column ``name`` names on ``queryset``'s model.

    Such a key names no row. Django answers an exact lookup with it with no
    rows where the backend states the range, from 5.0; where it states none,
    as Django 4.2's SQLite backend does, the lookup hands the key to the
    driver, which raises ``OverflowError``. So a caller asks this first and
    reads ``True`` as its own "no such row". ``name`` is read as a lookup's
    path is, by ``path_column``: a column's name or attname, ``pk``, or a path
    through relations, each held to the column it ends on
    (test_a_key_on_a_foreign_key_is_held_to_the_column_it_points_at,
    test_a_path_is_held_to_the_column_it_ends_on). A path that names no
    column, through a transform or a relation over more than one column, is
    ``False``, the lookup's alone. The key is
    read as the column's own lookup reads it, so a string of digits is the
    integer it spells, and a string that spells no number raises the
    ``ValueError`` the lookup would, in Django's words
    (test_a_key_that_spells_no_number_raises_as_the_lookup_did). A key of a
    type the column cannot read as a number, such as a row, is ``False``, the
    lookup's; ``None`` names no number either. An infinity is past every
    column (test_an_infinite_identifier_is_no_principal).
    """
    column = path_column(queryset.model, name)
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
    except OverflowError:
        # ``int`` of an infinite float, which no column holds.
        return True
    low, high = bounds
    # One arc to coverage, a condition each:
    # test_an_optional_key_sent_as_null_is_the_field_s (``None``, which no
    # range compares with) and
    # test_the_keys_at_either_end_of_the_column_s_range_are_matched (the
    # range, at both of its ends).
    return number is not None and not low <= number <= high


def choices_past_their_columns(form: forms.BaseForm) -> dict[str, list[ValidationError]]:
    """Each model choice field sent a key its integer column cannot hold, and its refusal.

    Django's ``ModelChoiceField`` matches its key with a query as it cleans,
    and ``ModelMultipleChoiceField`` its list with an ``in`` lookup, each
    handing a key past the column's range to the driver, which raises
    ``OverflowError``: for a list on every Django version, and for one key
    where the backend states no range, as Django 4.2's SQLite does. So the
    form's caller asks this before the form validates, and takes each field
    named off the form. Shared by ``FormValidator`` and by the selector
    applying a FilterSet's filters, whose model choice filters clean through
    the same two fields.

    The column is the one the field's ``to_field_name`` or its queryset's key
    names, held to its range as ``key_past_its_column`` holds a key, from the
    connection the field's queryset reads, so a string of digits is the
    integer it spells. A key no row can hold is refused as Django refuses a
    key no row holds: ``invalid_choice``, in the field's own words. A key the
    column reads as no number, such as ``"abc"``, the empty value or a model
    choice filter's ``null`` choice, is the field's
    (test_a_key_that_spells_no_number_is_the_field_s).
    """
    beyond: dict[str, list[ValidationError]] = {}
    for name, field in form.fields.items():
        # test_a_list_naming_a_key_past_the_column_s_range_is_no_choice fails
        # without this: its ``title`` has no rows to match.
        if not isinstance(field, forms.ModelChoiceField):
            continue
        # Never ``None``: ``FormValidator`` refuses a field with no queryset
        # when it is built, and django-filter builds a model choice filter's
        # field with one or not at all.
        queryset: Any = field.queryset
        # Read as the field reads it, through its widget at its prefixed
        # name: a ``QueryDict``'s item is only the last of a key's values
        # (test_a_list_s_key_past_its_column_is_refused_once). A field left
        # out reads as nothing sent, ``None`` or an empty list, past no
        # column.
        sent = field.widget.value_from_datadict(form.data, form.files, form.add_prefix(name))
        values = sent if isinstance(sent, list | tuple) else [sent]
        past = [
            value for value in values if _key_past(queryset, field.to_field_name or "pk", value)
        ]
        if past:
            beyond[name] = [
                ValidationError(
                    field.error_messages["invalid_choice"],
                    code="invalid_choice",
                    params={"value": past[0]},
                )
            ]
    return beyond


def _key_past(queryset: Any, name: str, key: Any) -> bool:
    """``key_past_its_column``, with a key that spells no number left to the field."""
    try:
        return key_past_its_column(queryset, name, key)
    except ValueError:
        return False
