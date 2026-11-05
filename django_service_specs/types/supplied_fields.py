"""``supplied_fields`` — the fields of an input its caller supplied.

The mutation helpers (``create_from_input``, ``update_from_input``,
``apply_input``) already drop ``UNSET`` values, so an input goes to them as it
is. This reader is for code that reads an input itself: a filter built from a
partial input, a payload handed to another system, a pre-fill from the row
being updated.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import Field, fields, is_dataclass
from typing import Any, ClassVar, Protocol

from django_service_specs.types.unset import UNSET


class _DataclassInstance(Protocol):
    # The standard library's own spelling of "a dataclass", which it keeps
    # only in its stubs, so a caller handing anything else is told so by the
    # type checker rather than at run time.
    __dataclass_fields__: ClassVar[dict[str, Field[Any]]]


def supplied_fields(data: _DataclassInstance | Mapping[str, object]) -> dict[str, Any]:
    """Return ``data``'s fields whose value is not ``UNSET``, in their order.

    ``data`` is a dataclass instance or a mapping. A dataclass gives its
    ``__init__`` fields only, as the mutation helpers read it: a field declared
    ``init=False`` is the dataclass's to compute, never the caller's to send.
    ``None`` is a supplied value and is kept.

    Shallow: a value is returned as it is, so a nested dataclass, a list of
    rows or a model instance is the caller's own object, its ``UNSET`` fields
    untouched. The values are typed ``Any`` because each is its own field's
    type, which no dict annotation can spell per key.

    Raises:
        TypeError: ``data`` is neither, a dataclass class among them.
    """
    if isinstance(data, Mapping):
        return {key: value for key, value in data.items() if value is not UNSET}
    if is_dataclass(data) and not isinstance(data, type):
        return {
            field.name: value
            for field in fields(data)
            if field.init and (value := getattr(data, field.name)) is not UNSET
        }
    raise TypeError(
        f"supplied_fields() takes a dataclass instance or a mapping, not {type(data).__name__!r}."
    )
