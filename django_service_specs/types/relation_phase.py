from __future__ import annotations

from enum import IntEnum


class RelationPhase(IntEnum):
    """The slot in the write sequence a relation kind belongs to."""

    FORWARD = 0
    REVERSE = 1
    GENERIC = 2
    M2M = 3


__all__ = ["RelationPhase"]
