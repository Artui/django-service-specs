from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FieldChange:
    """One field's before/after pair from a mutation."""

    field: str
    old: Any
    new: Any
