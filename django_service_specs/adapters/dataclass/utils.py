"""Reading a dataclass's annotations, and encoding a value back to JSON-like data.

Shared by the validator and the presenter, which read one declaration from two
sides: what an argument must be to decode into a field, and what a field's
value becomes when it is rendered. Reading it once, here, is what keeps the two
from disagreeing about a type. The scalar table and the unwrapping of
``Annotated`` and ``| None`` are shared with the other adapters, in
``adapters/utils.py``, for the same reason one level up.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import typing
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.db.models import Manager

from django_service_specs.adapters.utils import SCALARS, scalar_type, strip
from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.types.unset import UNSET

_SUPPORTED = (
    "str, int, float, bool, Decimal, datetime, date, a Literal, an Enum, "
    "a dataclass, or a list of any of these, each optionally '| None'"
)


@dataclass(frozen=True)
class Shape:
    """What one annotation means, once ``Annotated``, ``None`` and ``UnsetType`` are off it.

    ``python`` is what a value decodes into: the scalar class, the ``Enum``
    class, or the dataclass. It is ``None`` for a ``Literal``, whose values are
    already what the field holds, and for a list, which is ``items``.
    """

    type: str
    python: Any = None
    format: str | None = None
    nullable: bool = False
    choices: tuple[Any, ...] | None = None
    items: Shape | None = None
    fields: tuple[FieldShape, ...] | None = None

    @property
    def enum(self) -> type[Enum] | None:
        """The ``Enum`` class a choice decodes into, or ``None`` for a ``Literal``."""
        python = self.python
        if isinstance(python, type) and issubclass(python, Enum):
            return python
        return None


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
    """Refuse anything that is not a dataclass *type*, naming what was passed.

    An instance passes ``dataclasses.is_dataclass`` as well, and would fail
    later and further away, so the class is what is asked for.
    """
    if not (isinstance(cls, type) and dataclasses.is_dataclass(cls)):
        raise ImproperlyConfigured(f"{label} takes a dataclass type; got {cls!r}.")


def read_fields(cls: type[Any], stack: tuple[type[Any], ...] = ()) -> tuple[FieldShape, ...]:
    """Every field of ``cls``, in declaration order, with its annotation read.

    ``stack`` holds the dataclasses being read above this one. A dataclass
    that contains itself describes a tree of unbounded depth, which Parameters
    cannot declare, so it is refused by name rather than recursing until
    Python gives up.
    """
    if cls in stack:
        chain = " -> ".join(c.__qualname__ for c in (*stack, cls))
        raise ImproperlyConfigured(
            f"{chain}: a dataclass that contains itself describes a tree of unbounded "
            "depth, and a declaration is a finite one."
        )
    try:
        # ``include_extras`` keeps ``Annotated``, which is where a field's
        # FieldMarking is declared.
        hints = typing.get_type_hints(cls, include_extras=True)
    except NameError as exc:
        # The annotations are strings under ``from __future__ import
        # annotations``, resolved only now, against the module of ``cls``.
        raise ImproperlyConfigured(
            f"{cls.__qualname__}: an annotation names something not importable from its "
            f"module ({exc})."
        ) from exc
    below = (*stack, cls)
    out: list[FieldShape] = []
    for f in dataclasses.fields(cls):
        where = f"{cls.__qualname__}.{f.name}"
        shape, omittable, extras = _read(hints[f.name], where=where, stack=below)
        markings = [extra for extra in extras if isinstance(extra, FieldMarking)]
        if len(markings) > 1:
            raise ImproperlyConfigured(
                f"{where}: declares {len(markings)} FieldMarkings; a field has one audience."
            )
        out.append(
            FieldShape(
                name=f.name,
                shape=shape,
                field=f,
                omittable=omittable,
                marking=markings[0] if markings else None,
            )
        )
    return tuple(out)


def encode(shape: Shape, value: Any) -> Any:
    """``value`` as JSON-like data, read the way ``shape`` declares it.

    An object is read **by attribute**, one declared field at a time, so the
    value may be an instance of the dataclass or any object carrying the same
    names: a model row is the case this exists for. A field whose value is
    ``UNSET`` is left out rather than rendered, because it was never given one.

    A list may be a related manager, which is what a model row's reverse or
    many-to-many relation is, and is read through ``.all()`` so a prefetch is
    used when there is one.

    Scalars are encoded by what they are rather than by what the annotation
    says: a model's choice column holds a plain ``str`` where the dataclass
    declares an ``Enum``, and both encode to the value.
    """
    if value is None or value is UNSET:
        return value
    if shape.fields is not None:
        return encode_fields(shape.fields, value)
    if shape.items is not None:
        rows = value.all() if isinstance(value, Manager) else value
        return [encode(shape.items, row) for row in rows]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        # ``str`` and not ``float``: a float cannot hold every decimal, and a
        # decimal parameter is declared as a string for the same reason.
        return str(value)
    if isinstance(value, dt.date):
        # ``datetime`` subclasses ``date``, so this covers both.
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
    """(shape, omittable, extras) for one annotation, or ``ImproperlyConfigured``.

    Never a silent ``string``: an annotation this cannot map is refused where it
    is declared, naming the field, because a wrong type in a declaration is a
    schema that lies to every transport reading it.
    """
    base, nullable, omittable, extras = strip(annotation)
    origin = typing.get_origin(base)
    args = typing.get_args(base)
    if origin is typing.Literal:
        # ``Literal["a", None]`` is Python's own spelling of a nullable choice.
        values = tuple(v for v in args if v is not None)
        shape = Shape(
            _choice_type(values, base, where=where),
            nullable=nullable or len(values) != len(args),
            choices=values,
        )
    elif origin is list and len(args) == 1:
        # The element's shape keeps its own nullability, so decoding honours
        # ``list[int | None]``. What it cannot keep is a marking or
        # ``UnsetType``: a marking belongs to a field, and "may be omitted"
        # means nothing for one element of a list.
        items, _, _ = _read(args[0], where=where, stack=stack)
        shape = Shape("array", nullable=nullable, items=items)
    elif isinstance(base, type) and issubclass(base, Enum):
        values = tuple(member.value for member in base)
        shape = Shape(
            _choice_type(values, base, where=where),
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
        raise _unmappable(base, where=where)
    return shape, omittable, extras


def _choice_type(values: tuple[Any, ...], annotation: Any, *, where: str) -> str:
    """The one JSON type every choice has, or ``ImproperlyConfigured``.

    A choice set of mixed types has no single JSON type to declare, and a
    member whose value is not a JSON scalar cannot be sent at all.
    """
    found = {scalar_type(v) for v in values}
    json_type = found.pop() if len(found) == 1 else None
    if json_type is None:
        raise _unmappable(annotation, where=where)
    return json_type


def _unmappable(annotation: Any, *, where: str) -> ImproperlyConfigured:
    name = annotation.__qualname__ if isinstance(annotation, type) else repr(annotation)
    return ImproperlyConfigured(
        f"{where}: {name} has no JSON type this adapter can declare. Use {_SUPPORTED}."
    )
