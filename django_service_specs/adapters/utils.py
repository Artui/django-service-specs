"""Reading a type annotation, for every adapter whose library declares by annotation.

The dataclass adapter and the pydantic adapter both turn a field's annotation
into a JSON type, and they read it here so that the two cannot disagree: one
scalar table, one way of looking through ``Annotated`` and ``| None``, one
answer to what JSON type a value has. A ``Decimal`` is then the same parameter
whichever library declared it, which is what lets a transport describe a spec
without knowing which adapter it uses.

What each library adds on top - a nested dataclass or a nested model, a cycle
refused or a cycle bounded - is read in its own adapter. Nothing here imports a
validation library, so the dataclass adapter uses it without importing
pydantic.
"""

from __future__ import annotations

import datetime as dt
import types
import typing
from decimal import Decimal
from typing import Any

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


def scalar_type(value: Any) -> str | None:
    """The JSON type of a scalar value, or ``None`` for anything else.

    ``bool`` first: it subclasses ``int``, and ``true`` is not an integer on
    any wire this kernel has.
    """
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return None


def strip(annotation: Any) -> tuple[Any, bool, bool, tuple[Any, ...]]:
    """(base, nullable, omittable, Annotated extras) for one field's annotation.

    Loops rather than recursing because the wrappers nest either way round:
    ``Annotated[str | None, m]`` and ``Annotated[str, m] | None`` both mean a
    nullable string marked ``m``.
    """
    nullable = omittable = False
    extras: list[Any] = []
    while True:
        origin = typing.get_origin(annotation)
        if origin is typing.Annotated:
            base, *metadata = typing.get_args(annotation)
            extras.extend(metadata)
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
            # ``int | str`` has no single JSON type, and neither does a union
            # of only ``None`` and ``UnsetType``. Both fall through to the
            # caller's refusal as the annotation they are.
            if len(arms) != 1:
                return annotation, nullable, omittable, tuple(extras)
            annotation = arms[0]
        else:
            return annotation, nullable, omittable, tuple(extras)
