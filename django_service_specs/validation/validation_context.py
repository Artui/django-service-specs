from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class ValidationContext:
    """The principal, the target, whether the call is partial, its seeds, and the call's context."""

    principal: Any
    target: Any = None
    partial: bool = False
    ambient: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}), compare=False)
    resolved: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}), compare=False)
    call_context: dict[str, Any] = field(default_factory=dict, compare=False)
