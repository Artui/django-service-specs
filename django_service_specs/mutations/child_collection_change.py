from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ChildCollectionChange:
    """What a nested write did to one relation that holds a collection."""

    relation: str
    created: tuple[Any, ...] = field(default_factory=tuple)
    updated: tuple[Any, ...] = field(default_factory=tuple)
    deleted: tuple[Any, ...] = field(default_factory=tuple)
    unlinked: tuple[Any, ...] = field(default_factory=tuple)
    removed: tuple[Any, ...] = field(default_factory=tuple)

    def __bool__(self) -> bool:
        return bool(self.created or self.updated or self.deleted or self.unlinked or self.removed)


__all__ = ["ChildCollectionChange"]
