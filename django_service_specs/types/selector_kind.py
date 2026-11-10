from __future__ import annotations

from enum import Enum


class SelectorKind(str, Enum):
    """The shape a selector spec returns."""

    LIST = "list"
    RETRIEVE = "retrieve"
