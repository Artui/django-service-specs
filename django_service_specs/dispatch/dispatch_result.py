"""``DispatchResult`` - what one dispatch produced."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class DispatchResult:
    """The value an operation produced, and how to read it.

    Not-found is **reported, not raised**: a required row that does not exist
    comes back as ``kind="not_found"`` and the transport decides what that
    means on its wire - a 404, an exit code, a tool error. Nothing here is a
    status code, because most transports have none.

    Attributes:
        kind: ``"instance"`` (one value, possibly ``None``), ``"list"`` (a
            collection, a queryset when it can be one), or ``"not_found"``.
        value: What to present: the selector's rows, or the service's return,
            or what its output selector re-read.
        service_result: The service's own return, before any output selector.
        instance: The resolved target - the row, or the collection's queryset.
        data: The validated values the service received.
    """

    kind: Literal["instance", "list", "not_found"]
    value: Any = None
    service_result: Any = None
    instance: Any = None
    data: Any = None
