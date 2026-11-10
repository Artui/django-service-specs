from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def null_progress(
    progress: float,
    *,
    total: float | None = None,
    message: str | None = None,
    meta: Mapping[str, Any] | None = None,
) -> None:
    """The ``ProgressReporter`` for a transport with nowhere to send progress."""
    del progress, total, message, meta
