from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OutputPage:
    """One page of rows, plus what a caller needs to know to ask for the next."""

    items: Any
    page: int
    limit: int
    total: int

    @property
    def total_pages(self) -> int:
        """How many pages exist at this ``limit``."""
        return max(1, -(-self.total // self.limit))

    @property
    def has_next(self) -> bool:
        """Whether asking for ``page + 1`` would return anything."""
        return self.page < self.total_pages

    def envelope(self, rendered: Any) -> dict[str, Any]:
        """Wrap already-presented rows in the published paging envelope."""
        return {
            "items": rendered,
            "page": self.page,
            "totalPages": self.total_pages,
            "hasNext": self.has_next,
        }
