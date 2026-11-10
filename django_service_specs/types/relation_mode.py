from __future__ import annotations

from enum import Enum


class RelationMode(str, Enum):
    """How a relation reconciles the rows the payload leaves out."""

    REPLACE = "replace"
    """The incoming set is authoritative; rows it leaves out are disposed of."""

    MERGE = "merge"
    """The incoming set upserts and removes nothing."""


__all__ = ["RelationMode"]
