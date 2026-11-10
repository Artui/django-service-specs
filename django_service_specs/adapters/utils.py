from __future__ import annotations

import datetime as dt
import types
import typing
from decimal import Decimal
from enum import Enum
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.db.models import Choices
from django.db.models.manager import BaseManager

from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.types.unset import UnsetType

SCALARS: dict[type, tuple[str, str | None]] = {
    str: ("string", None),
    int: ("integer", None),
    float: ("number", None),
    bool: ("boolean", None),
    # JSON has no decimal, date-time or date, so each travels as a string and
    # the format names what the string decodes into.
    Decimal: ("string", "decimal"),
    dt.datetime: ("string", "date-time"),
    dt.date: ("string", "date"),
}
"""The scalar annotations and their JSON type and format. Looked up by
identity, so ``bool`` is not read as ``int`` and ``datetime`` is not read as
``date``, although each subclasses the other."""


def element_format(fmt: str | None) -> str | None:
    """The format an array declares for its element, given the element's own."""
    return fmt if fmt == "decimal" else None


def scalar_type(value: Any) -> str | None:
    """The JSON type of a scalar value, or ``None`` for anything else."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return None


def shared_scalar_type(values: tuple[Any, ...]) -> str | None:
    """The one JSON type every value has, or ``None`` when they have none or several."""
    found = {scalar_type(value) for value in values}
    return found.pop() if len(found) == 1 else None


def choice_type(values: tuple[Any, ...], annotation: Any, *, where: str, supported: str) -> str:
    """The one JSON type every choice has, or ``ImproperlyConfigured``."""
    json_type = shared_scalar_type(values)
    if json_type is None:
        raise unmappable(annotation, where=where, supported=supported)
    return json_type


def unmappable(annotation: Any, *, where: str, supported: str) -> ImproperlyConfigured:
    """The refusal of an annotation with no JSON type, naming the field and what is read."""
    plain = isinstance(annotation, type) and typing.get_origin(annotation) is None
    name = annotation.__qualname__ if plain else repr(annotation)
    return ImproperlyConfigured(
        f"{where}: {name} has no JSON type this adapter can declare. Use {supported}."
    )


def enum_class(python: Any) -> type[Enum] | None:
    """``python`` when it is an ``Enum`` class, which a choice decodes into, else ``None``."""
    if isinstance(python, type) and issubclass(python, Enum):
        return python
    return None


def marking(extras: tuple[Any, ...], *, where: str) -> FieldMarking | None:
    """The one ``FieldMarking`` among a field's ``Annotated`` extras, if any."""
    markings = [extra for extra in extras if isinstance(extra, FieldMarking)]
    if len(markings) > 1:
        raise ImproperlyConfigured(
            f"{where}: declares {len(markings)} FieldMarkings; a field has one audience."
        )
    return markings[0] if markings else None


def rows_of(value: Any) -> Any:
    """A list field's value, read through ``.all()`` when it is a related manager."""
    return value.all() if isinstance(value, BaseManager) else value


def choice_labels(enum_cls: type[Enum] | None) -> tuple[tuple[Any, str], ...] | None:
    """Each value of a Django ``Choices`` enum with its label, or ``None``."""
    if enum_cls is None or not issubclass(enum_cls, Choices):
        return None
    return tuple((member.value, member.label) for member in enum_cls)


def choice_pairs(
    choices: tuple[Any, ...] | None, enum_cls: type[Enum] | None
) -> tuple[tuple[Any, str], ...] | None:
    """An output field's (value, display) pairs: a ``Choices`` label, else the value's ``str``."""
    if choices is None:
        return None
    labels = choice_labels(enum_cls)
    if labels is not None:
        return tuple((value, str(label)) for value, label in labels)
    return tuple((value, str(value)) for value in choices)


def strip(annotation: Any) -> tuple[Any, bool, bool, tuple[Any, ...]]:
    """(base, nullable, omittable, Annotated extras) for one field's annotation."""
    nullable = omittable = False
    extras: list[Any] = []
    while True:
        origin = typing.get_origin(annotation)
        if origin is typing.Annotated:
            base, *metadata = typing.get_args(annotation)
            extras[:0] = metadata
            annotation = base
        elif origin in (typing.Union, types.UnionType):
            arms = []
            for arm in typing.get_args(annotation):
                if arm is type(None):
                    nullable = True
                elif arm is UnsetType:
                    omittable = True
                else:
                    arms.append(arm)
            if len(arms) != 1:
                return annotation, nullable, omittable, tuple(extras)
            annotation = arms[0]
        else:
            return annotation, nullable, omittable, tuple(extras)
