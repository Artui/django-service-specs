from __future__ import annotations

import typing
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from enum import Enum
from typing import Any

from annotated_types import GroupedMetadata, MaxLen, MinLen
from django.core.exceptions import ImproperlyConfigured
from pydantic import BaseModel, RootModel
from pydantic.errors import PydanticUndefinedAnnotation
from pydantic.fields import ComputedFieldInfo, FieldInfo
from pydantic_core import PydanticUndefined

from django_service_specs.adapters.utils import (
    SCALARS,
    choice_type,
    enum_class,
    marking,
    strip,
    unmappable,
)
from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.types.unset import UNSET

MAX_APPEARANCES = 4
"""How many times one model may appear on a path before the next appearance is truncated.

A self-referential model - a category tree, a threaded comment, an org chart -
is an ordinary shape, and described without a bound it is a ``RecursionError``
raised while a spec is being *declared*, before any call exists to fail. So the
bound has no off switch. The root is the first appearance, so a tree is
described four levels deep and the fifth level is an ``object`` with no
``fields``: still true, since it is an object a caller can send, and
constraining nothing a valid call could fail against. A list of them is an
array of ``"object"``.

Appearances are counted per path, not per model: the same address model under
``billing`` and ``shipping`` is on two paths and is described in full on both.
Four is drfs' ``_MAX_SERIALIZER_APPEARANCES``, so a pydantic declaration and a
DRF one are cut at the same depth.

Truncation costs the **shape check** its depth and nothing else. The kernel
checks what the declaration describes; below the cut, the model's own schema
still validates every level, because pydantic builds the instances, not this
adapter.
"""

_SUPPORTED = (
    "str, int, float, bool, Decimal, datetime, date, a Literal, an Enum, a pydantic "
    "model, dict[str, ...], or a list of any of these, each optionally '| None'"
)


@dataclass(frozen=True)
class Shape:
    """What one annotation means, once ``Annotated`` and ``None`` are off it."""

    type: str
    python: Any = None
    format: str | None = None
    nullable: bool = False
    choices: tuple[Any, ...] | None = None
    items: Shape | None = None
    fields: tuple[FieldShape, ...] | None = None

    @property
    def enum(self) -> type[Enum] | None:
        """The ``Enum`` class a choice validates into, or ``None`` for a ``Literal``."""
        return enum_class(self.python)

    @property
    def model(self) -> type[BaseModel] | None:
        """The model an object validates into, truncated or not; ``None`` for anything else."""
        python = self.python
        return python if _is_model(python) else None


@dataclass(frozen=True)
class FieldShape:
    """One model field, or one computed field, with everything the adapters read off it."""

    name: str
    shape: Shape
    computed: bool
    input_name: str
    output_name: str | None
    required: bool
    default: Any
    """The declared default when JSON can state it, else ``UNSET``."""
    help: str | None
    label: str | None
    always_present: bool
    marking: FieldMarking | None
    min_length: int | None = None
    max_length: int | None = None
    """How many elements a list field takes, as the model declares it; ``None``
    for a bound it leaves open, and for every field that is not a list."""


def check_model(model: Any, *, label: str) -> None:
    """Refuse anything that is not a pydantic model class, naming what was passed."""
    if not _is_model(model):
        raise ImproperlyConfigured(
            f"{label} takes a pydantic model class (not a RootModel, which validates one "
            f"value rather than named arguments); got {model!r}."
        )


def read_fields(
    model: type[BaseModel], stack: tuple[type[BaseModel], ...] = ()
) -> tuple[FieldShape, ...]:
    """Every field of ``model`` in declaration order, then every computed field."""
    _complete(model)
    below = (*stack, model)
    by_alias = model.model_config.get("validate_by_alias", True)
    out: list[FieldShape] = []
    for name, info in model.model_fields.items():
        where = f"{model.__qualname__}.{name}"
        shape, extras = _read(info.annotation, where=where, stack=below)
        metadata = (*extras, *info.metadata)
        min_length, max_length = _lengths(shape, metadata)
        out.append(
            FieldShape(
                name=name,
                shape=shape,
                computed=False,
                input_name=_input_name(name, info, by_alias=by_alias, where=where),
                output_name=None if info.exclude else _output_name(name, info),
                required=info.is_required(),
                default=_default(info),
                help=info.description,
                label=info.title,
                always_present=_always_present(info),
                marking=marking(metadata, where=where),
                min_length=min_length,
                max_length=max_length,
            )
        )
    for name, computed in model.model_computed_fields.items():
        where = f"{model.__qualname__}.{name}"
        shape, extras = _read(computed.return_type, where=where, stack=below)
        out.append(
            FieldShape(
                name=name,
                shape=shape,
                computed=True,
                input_name=name,
                output_name=computed.alias or name,
                required=False,
                default=UNSET,
                help=computed.description,
                label=computed.title,
                always_present=_always_present(computed),
                marking=marking(extras, where=where),
            )
        )
    return tuple(out)


def fields_of(shape: Shape) -> tuple[FieldShape, ...]:
    """A model node's fields: as read, or read afresh where the appearance bound cut them."""
    return shape.fields if shape.fields is not None else read_fields(shape.python)


def inputs(fields: tuple[FieldShape, ...]) -> tuple[FieldShape, ...]:
    """The fields a caller supplies: every model field, and no computed one."""
    return tuple(fs for fs in fields if not fs.computed)


def is_json_native(value: Any) -> bool:
    """Whether ``value`` survives a JSON round trip as itself, containers included."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return True
    if isinstance(value, (list, tuple)):
        return all(is_json_native(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and is_json_native(item) for key, item in value.items())
    return False


def _is_model(value: Any) -> bool:
    # One branch to coverage, so its condition has its own test.
    return (
        isinstance(value, type)
        and issubclass(value, BaseModel)
        and not issubclass(value, RootModel)
    )


def _complete(model: type[BaseModel]) -> None:
    """Resolve a model whose annotations named a class not yet defined."""
    if model.__pydantic_complete__:
        return
    try:
        model.model_rebuild()
    except PydanticUndefinedAnnotation as exc:
        raise ImproperlyConfigured(
            f"{model.__qualname__}: an annotation names something not importable from its "
            f"module ({exc})."
        ) from exc


def _input_name(name: str, info: FieldInfo, *, by_alias: bool, where: str) -> str:
    """The one key pydantic validates this field by: the parameter's name."""
    if not by_alias:
        return name
    alias = info.validation_alias
    if alias is None:
        return info.alias or name
    if isinstance(alias, str):
        return alias
    raise ImproperlyConfigured(
        f"{where}: validation_alias {alias!r} is not one name, and a parameter has one. "
        "Use a string alias."
    )


def _output_name(name: str, info: FieldInfo) -> str:
    """The key ``model_dump(by_alias=True)`` emits for this field."""
    return info.serialization_alias or info.alias or name


def _default(info: FieldInfo) -> Any:
    # A ``default_factory``'s value is per instance, so it is not a printable default.
    default = info.default
    if default is PydanticUndefined or not is_json_native(default):
        return UNSET
    return default


def _always_present(info: FieldInfo | ComputedFieldInfo) -> bool:
    # ``model_dump`` emits every key, except one whose ``exclude_if`` holds for the value at hand.
    return getattr(info, "exclude_if", None) is None


def _lengths(shape: Shape, metadata: tuple[Any, ...]) -> tuple[int | None, int | None]:
    """(min_length, max_length) a list field declares, each ``None`` where it declares none."""
    if shape.type != "array":
        return None, None
    min_length = max_length = None
    for item in _flatten(metadata):
        if isinstance(item, MinLen):
            min_length = item.min_length
        elif isinstance(item, MaxLen):
            max_length = item.max_length
    return min_length, max_length


def _flatten(metadata: Iterable[Any]) -> Iterator[Any]:
    """Each piece of metadata, with every group opened where it stands."""
    for item in metadata:
        if isinstance(item, FieldInfo):
            yield from _flatten(item.metadata)
        elif isinstance(item, GroupedMetadata):
            yield from _flatten(item)
        else:
            yield item


def _read(
    annotation: Any, *, where: str, stack: tuple[type[BaseModel], ...]
) -> tuple[Shape, tuple[Any, ...]]:
    """(shape, ``Annotated`` extras) for one annotation, or ``ImproperlyConfigured``."""
    base, nullable, omittable, extras = strip(annotation)
    if omittable:
        raise unmappable(annotation, where=where, supported=_SUPPORTED)
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
        items, _ = _read(args[0], where=where, stack=stack)
        shape = Shape("array", nullable=nullable, items=items)
    elif origin is dict and args[:1] == (str,):
        shape = Shape("object", python=dict, nullable=nullable)
    elif isinstance(base, type) and issubclass(base, Enum):
        values = tuple(member.value for member in base)
        shape = Shape(
            choice_type(values, base, where=where, supported=_SUPPORTED),
            python=base,
            nullable=nullable,
            choices=values,
        )
    elif _is_model(base):
        fields = None if stack.count(base) >= MAX_APPEARANCES else read_fields(base, stack)
        shape = Shape("object", python=base, nullable=nullable, fields=fields)
    elif isinstance(base, type) and base in SCALARS:
        json_type, fmt = SCALARS[base]
        shape = Shape(json_type, python=base, format=fmt, nullable=nullable)
    else:
        raise unmappable(base, where=where, supported=_SUPPORTED)
    return shape, extras
