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
