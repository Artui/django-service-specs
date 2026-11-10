from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from django_service_specs.output.presentation_context import PresentationContext


@dataclass(frozen=True)
class DispatchResult:
    """The value an operation produced, and how to read it."""

    kind: Literal["instance", "list", "not_found"]
    value: Any = None
    service_result: Any = None
    instance: Any = None
    data: Any = None
    context: PresentationContext | None = field(default=None, compare=False)
