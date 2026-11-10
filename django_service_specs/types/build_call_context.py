from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.types.transport_key import TRANSPORT_KEY

# Spelled here rather than read from ``CALL_SEEDS``: ``types/`` imports nothing
# else in the package, and ``format`` and ``action`` are no call seeds anyway.
_STANDARD_KEYS = ("request", "view", "format", "action")


def build_call_context(
    transport: str,
    *,
    base: Mapping[str, Any] | None = None,
    request: Any = None,
    view: Any = None,
    format: str | None = None,
    action: str | None = None,
) -> dict[str, Any]:
    """Return a new ``call_context`` for one call, stamped with ``transport``."""
    given = {
        name: value
        for name, value in zip(_STANDARD_KEYS, (request, view, format, action), strict=True)
        if value is not None
    }
    return {
        **dict.fromkeys(_STANDARD_KEYS),
        **(base or {}),
        **given,
        TRANSPORT_KEY: transport,
    }
