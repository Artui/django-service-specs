from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class ProgressReporter(Protocol):
    """How a long-running service reports how far it has got."""

    def __call__(
        self,
        progress: float,
        *,
        total: float | None = None,
        message: str | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> None: ...
