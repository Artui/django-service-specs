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
    """Every message Django's ``errors`` carry, in Django's words and with Django's code."""
    return [
        CodedMessage(_rendered(leaf), leaf.code or "invalid")
        for error in errors
        for leaf in _leaves(error)
    ]


def _leaves(error: ValidationError) -> list[ValidationError]:
    """The one-message errors ``error`` holds: its list, or each field's list in turn."""
    if hasattr(error, "error_dict"):
        return [leaf for field in error.error_dict.values() for leaf in field]
    return error.error_list


def _rendered(leaf: ValidationError) -> str:
    """A one-message error's words, as ``ValidationError.__iter__`` renders them."""
    message = leaf.message
    if leaf.params:
        message %= leaf.params
    return str(message)


def length_problem(param: Parameter, count: int) -> CodedMessage | None:
    """The refusal of an array of ``count`` elements, or ``None`` if ``param`` takes it."""
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
    """The number ``text`` spells as an ``integer`` or ``number``, or ``None``."""
    if not text.isascii():
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
        return int(text)
    except ValueError:
        return number if any(mark in text for mark in ".eE") else None


def unknown_arguments_policy(value: UnknownArguments | str) -> UnknownArguments:
    """``value`` as a policy: a member, or its plain value, refusing what is not a policy."""
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
    """The integers ``field``'s column holds on the database ``using``, or ``None``."""
    if not isinstance(field, IntegerField):
        return None
    low, high = connections[using].ops.integer_field_range(field.get_internal_type())
    return (
        WIDEST_INTEGER[0] if low is None else low,
        WIDEST_INTEGER[1] if high is None else high,
    )


def integer_range_refusal(number: int, bounds: tuple[int, int]) -> ValidationError | None:
    """The refusal of ``number`` past ``bounds``, an integer column's range, or ``None``."""
    low, high = bounds
    try:
        MinValueValidator(low)(number)
        MaxValueValidator(high)(number)
    except ValidationError as error:
        return error
    return None


def path_column(model: type[Model], path: str) -> Any:
    """The column a lookup path on ``model`` compares with, or ``None``."""
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
            return None
    return column


def key_past_its_column(queryset: Any, name: str, key: Any) -> bool:
    """Whether ``key`` is past the range of the integer column ``name`` on the model."""
    column = path_column(queryset.model, name)
    bounds = integer_column_range(column, queryset.db)
    if bounds is None:
        return False
    try:
        number = column.get_prep_value(key)
    except TypeError:
        return False
    except OverflowError:
        return True
    low, high = bounds
    return number is not None and not low <= number <= high


def choices_past_their_columns(form: forms.BaseForm) -> dict[str, list[ValidationError]]:
    """Each model choice field sent a key its integer column cannot hold, and its refusal."""
    beyond: dict[str, list[ValidationError]] = {}
    for name, field in form.fields.items():
        if not isinstance(field, forms.ModelChoiceField):
            continue
        queryset: Any = field.queryset
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
