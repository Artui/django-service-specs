from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

F = TypeVar("F")


def implements(proto: type[F]) -> Callable[[F], F]:
    """Return the decorated callable unchanged, typed as conforming to ``proto``."""

    def _identity(fn: F) -> F:
        return fn

    return _identity
