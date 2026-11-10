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
    """Return ``data``'s fields whose value is not ``UNSET``, in their order."""
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
