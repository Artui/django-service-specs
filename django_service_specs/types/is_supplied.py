"""``is_supplied`` — whether a value was supplied, as a narrowing the type checker reads.

``value is not UNSET`` says the same at run time and narrows nothing, because
``UNSET`` is a value and a type checker narrows a union by type. A field
declared ``str | None | UnsetType`` stays that whole union after the identity
check, so every read past it needs a cast. This predicate is the one place
that check is spelled as a ``TypeIs``.
"""

from __future__ import annotations

from typing import TypeVar

from typing_extensions import TypeIs

from django_service_specs.types.unset import UNSET, UnsetType

T = TypeVar("T")


def is_supplied(value: T | UnsetType) -> TypeIs[T]:
    """Return True if ``value`` is anything but ``UNSET``, ``None`` included.

    A type checker narrows ``value`` to ``T`` where this returns True: a
    ``str | None | UnsetType`` becomes ``str | None``, an attribute read
    (``patch.bio``) included. Where it returns False the value is ``UNSET``.
    """
    return value is not UNSET
