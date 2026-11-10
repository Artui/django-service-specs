from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def coded(detail: Any) -> Any:
    """``detail`` with every message read as ``(message, code)``."""
    if isinstance(detail, Mapping):
        return {key: coded(value) for key, value in detail.items()}
    if isinstance(detail, list):
        return [coded(message) for message in detail]
    return (str(detail), getattr(detail, "code", None))
