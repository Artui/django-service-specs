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

The forms adapter reads field instances rather than annotations and shares
``scalar_type``, since a typed choice field's values take their JSON type from
it exactly as a ``Literal``'s do, and ``element_format``, since a
``ModelMultipleChoiceField`` keyed on a decimal column is a list of decimals as
``list[Decimal]`` is.

``choice_labels`` reads Django's own vocabulary rather than an annotation's,
and both annotation adapters label an enum's choices through it, so a
``TextChoices`` field is labelled alike whichever library declared it.
"""

from __future__ import annotations

import datetime as dt
import types
import typing
from decimal import Decimal
from enum import Enum
from typing import Any

from django.db.models import Choices

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
    """The format an array declares for its element, given the element's own.

    An array's format describes each element, and ``Parameter`` takes only
    ``decimal`` there: the one format a flat reader may split on commas and
    the shape check reads each element as. So a list of decimals is declared
    as the scalar is, a string in the ``decimal`` format that takes a JSON
    number too, while a list of dates or date-times stays an array of strings
    for its Validator to decode. Held by
    test_a_list_of_decimals_declares_each_element_a_decimal in the dataclass
    and pydantic adapters and by
    test_a_list_of_keys_declares_each_element_a_decimal_as_one_key_does in the
    forms adapter: returning the element's format whole, a list of dates is
    refused when declared.
    """
    return fmt if fmt == "decimal" else None


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


def choice_labels(enum_cls: type[Enum] | None) -> tuple[tuple[Any, str], ...] | None:
    """Each value of a Django ``Choices`` enum with its label, or ``None``.

    Only a ``Choices`` enum has a label for a reader. A plain ``Enum``'s member
    names are identifiers, and a ``Literal`` has nothing but its values, so
    neither is labelled, as neither has a display in the presenters. The label
    is handed on unrendered: a lazy translation stays lazy until a schema
    renders it, in the language active then, since an adapter may build its
    Parameters once.
    """
    # One branch to coverage, so each operand is held by its own test:
    # test_a_literal_has_no_labels (no enum) and test_a_plain_enum_has_no_labels.
    if enum_cls is None or not issubclass(enum_cls, Choices):
        return None
    return tuple((member.value, member.label) for member in enum_cls)


def strip(annotation: Any) -> tuple[Any, bool, bool, tuple[Any, ...]]:
    """(base, nullable, omittable, Annotated extras) for one field's annotation.

    Loops rather than recursing because the wrappers nest either way round:
    ``Annotated[str | None, m]`` and ``Annotated[str, m] | None`` both mean a
    nullable string marked ``m``.

    The extras run from the innermost ``Annotated`` out, each in the order it
    was written: the order a library building the type applies them in, which
    is what decides between two lengths on one list. Held by
    test_every_spelling_of_a_list_s_length_is_declared, whose ``deep`` row
    reads the outer length with them collected the other way round.
    """
    nullable = omittable = False
    extras: list[Any] = []
    while True:
        origin = typing.get_origin(annotation)
        if origin is typing.Annotated:
            base, *metadata = typing.get_args(annotation)
            # Found outside in, so each layer goes ahead of the ones already found.
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
            # ``int | str`` has no single JSON type, and neither does a union
            # of only ``None`` and ``UnsetType``. Both fall through to the
            # caller's refusal as the annotation they are.
            if len(arms) != 1:
                return annotation, nullable, omittable, tuple(extras)
            annotation = arms[0]
        else:
            return annotation, nullable, omittable, tuple(extras)
