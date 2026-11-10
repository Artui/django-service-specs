from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class PresentationContext:
    """The principal a call ran for, its target, its seeds, its context and its shapes."""

    principal: Any
    target: Any = None
    ambient: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}), compare=False)
    call_context: dict[str, Any] = field(default_factory=dict, compare=False)
    shapes: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}), compare=False)
