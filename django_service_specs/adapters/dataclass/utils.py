from __future__ import annotations

import dataclasses
import datetime as dt
import typing
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.adapters.utils import (
    SCALARS,
    choice_type,
    enum_class,
    marking,
    rows_of,
    stated_lengths,
    strip,
    unmappable,
)
from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.types.unset import UNSET

_SUPPORTED = (
    "str, int, float, bool, Decimal, datetime, date, a Literal, an Enum, "
    "a dataclass, dict[str, ...], or a list or tuple[X, ...] of any of these, "
    "each optionally '| None'"
)


@dataclass(frozen=True)
class Shape:
    """What one annotation means, once ``Annotated``, ``None`` and ``UnsetType`` are off it."""

    type: str
    python: Any = None
    format: str | None = None
    nullable: bool = False
    choices: tuple[Any, ...] | None = None
    items: Shape | None = None
    fields: tuple[FieldShape, ...] | None = None
    values: Shape | None = None
    min_length: int | None = None
    max_length: int | None = None

    @property
    def enum(self) -> type[Enum] | None:
        """The ``Enum`` class a choice decodes into, or ``None`` for a ``Literal``."""
        return enum_class(self.python)


@dataclass(frozen=True)
class FieldShape:
    """One dataclass field: its shape, and what the field itself declares."""

    name: str
    shape: Shape
    field: dataclasses.Field[Any]
    omittable: bool
    """The annotation admits ``UnsetType``: the argument may be left out and the
    value stays ``UNSET``. It adds no JSON type, since no wire can send it."""
    marking: FieldMarking | None

    @property
    def has_default(self) -> bool:
        return (
            self.field.default is not dataclasses.MISSING
            or self.field.default_factory is not dataclasses.MISSING
        )

    @property
    def required(self) -> bool:
        return not self.has_default and not self.omittable


def check_dataclass(cls: Any, *, label: str) -> None:
    """Refuse anything that is not a dataclass *type*, naming what was passed."""
    if not (isinstance(cls, type) and dataclasses.is_dataclass(cls)):
        raise ImproperlyConfigured(f"{label} takes a dataclass type; got {cls!r}.")


def read_fields(cls: type[Any], stack: tuple[type[Any], ...] = ()) -> tuple[FieldShape, ...]:
    """Every field of ``cls``, in declaration order, with its annotation read."""
    if cls in stack:
        chain = " -> ".join(c.__qualname__ for c in (*stack, cls))
        raise ImproperlyConfigured(
            f"{chain}: a dataclass that contains itself describes a tree of unbounded "
            "depth, and a declaration is a finite one."
        )
    try:
        hints = typing.get_type_hints(cls, include_extras=True)
    except NameError as exc:
        raise ImproperlyConfigured(
            f"{cls.__qualname__}: an annotation names something not importable from its "
            f"module ({exc})."
        ) from exc
    below = (*stack, cls)
    out: list[FieldShape] = []
    for f in dataclasses.fields(cls):
        where = f"{cls.__qualname__}.{f.name}"
        shape, omittable, extras = _read(hints[f.name], where=where, stack=below)
        _check_default_length(shape, f.default, where=where)
        out.append(
            FieldShape(
                name=f.name,
                shape=shape,
                field=f,
                omittable=omittable,
                marking=marking(extras, where=where),
            )
        )
    return tuple(out)


def encode(shape: Shape, value: Any) -> Any:
    """``value`` as JSON-like data, read the way ``shape`` declares it."""
    if value is None or value is UNSET:
        return value
    if shape.fields is not None:
        return encode_fields(shape.fields, value)
    if shape.items is not None:
        return [encode(shape.items, row) for row in rows_of(value)]
    if shape.values is not None:
        return {key: encode(shape.values, item) for key, item in value.items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dt.date):
        return value.isoformat()
    return value


def encode_fields(fields: tuple[FieldShape, ...], value: Any) -> dict[str, Any]:
    """Each declared field of ``value``, read by attribute and encoded; ``UNSET`` left out."""
    encoded: dict[str, Any] = {}
    for fs in fields:
        field_value = getattr(value, fs.name)
        if field_value is not UNSET:
            encoded[fs.name] = encode(fs.shape, field_value)
    return encoded


def _read(
    annotation: Any, *, where: str, stack: tuple[type[Any], ...]
) -> tuple[Shape, bool, tuple[Any, ...]]:
    """(shape, omittable, extras) for one annotation, or ``ImproperlyConfigured``."""
    base, nullable, omittable, extras = strip(annotation)
    origin = typing.get_origin(base)
    args = typing.get_args(base)
    if origin is typing.Literal:
        values = tuple(v for v in args if v is not None)
        shape = Shape(
            choice_type(values, base, where=where, supported=_SUPPORTED),
            nullable=nullable or len(values) != len(args),
            choices=values,
        )
    elif origin is list and len(args) == 1:
        items, _, _ = _read(args[0], where=where, stack=stack)
        shape = Shape("array", python=list, nullable=nullable, items=items)
    elif origin is tuple and len(args) == 2 and args[1] is Ellipsis:
        items, _, _ = _read(args[0], where=where, stack=stack)
        shape = Shape("array", python=tuple, nullable=nullable, items=items)
    elif origin is dict and args[:1] == (str,):
        values, _, _ = _read(args[1], where=where, stack=stack)
        shape = Shape("object", python=dict, nullable=nullable, values=values)
    elif isinstance(base, type) and issubclass(base, Enum):
        values = tuple(member.value for member in base)
        shape = Shape(
            choice_type(values, base, where=where, supported=_SUPPORTED),
            python=base,
            nullable=nullable,
            choices=values,
        )
    elif isinstance(base, type) and dataclasses.is_dataclass(base):
        shape = Shape("object", python=base, nullable=nullable, fields=read_fields(base, stack))
    elif isinstance(base, type) and base in SCALARS:
        json_type, fmt = SCALARS[base]
        shape = Shape(json_type, python=base, format=fmt, nullable=nullable)
    else:
        raise unmappable(base, where=where, supported=_SUPPORTED)
    min_length, max_length = _lengths(extras, where=where)
    if min_length is None and max_length is None:
        return shape, omittable, extras
    if base is not str:
        raise ImproperlyConfigured(
            f"{where}: a MinLen, MaxLen or Len is read on a plain str only, the one annotation "
            "whose length this adapter holds a value to."
        )
    return (
        dataclasses.replace(shape, min_length=min_length, max_length=max_length),
        omittable,
        extras,
    )


def _lengths(extras: tuple[Any, ...], *, where: str) -> tuple[int | None, int | None]:
    """(min_length, max_length) the ``annotated_types`` among ``extras`` state, the last of each."""
    stated_min, stated_max, others = stated_lengths(extras)
    if others:
        raise ImproperlyConfigured(
            f"{where}: a group of constraints also states {list(others)!r}, which this adapter "
            "does not apply; only a MinLen or MaxLen is read, so state the rest in the "
            "service or validate with a pydantic model."
        )
    min_length = None if stated_min is None else _count(stated_min, where=where)
    max_length = None if stated_max is None else _count(stated_max, where=where)
    if min_length is not None and max_length is not None and min_length > max_length:
        raise ImproperlyConfigured(
            f"{where}: a minimum length of {min_length} past the maximum of {max_length} "
            "takes no string."
        )
    return min_length, max_length


def _count(value: Any, *, where: str) -> int:
    """A length as stated, refused unless it is a whole count of characters."""
    if type(value) is not int or value < 0:
        raise ImproperlyConfigured(f"{where}: a length is a count of characters; got {value!r}.")
    return value


def _check_default_length(shape: Shape, default: Any, *, where: str) -> None:
    """Refuse a ``str`` default outside the lengths its own field states."""
    if not isinstance(default, str):
        return
    if shape.max_length is not None and len(default) > shape.max_length:
        bound = f"a maximum length of {shape.max_length}"
    elif shape.min_length is not None and len(default) < shape.min_length:
        bound = f"a minimum length of {shape.min_length}"
    else:
        return
    raise ImproperlyConfigured(
        f"{where}: the default {default!r} is outside {bound} the field states, so a call "
        "leaving it out would hand on a value no caller could send."
    )
