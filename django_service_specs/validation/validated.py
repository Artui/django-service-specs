from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Validated:
    """The values a call's service is called with, its ``data``, and what else it binds."""

    values: dict[str, Any]
    data: Any
    pool: Mapping[str, Any] = field(default_factory=dict)
