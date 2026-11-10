from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.types.transport_key import TRANSPORT_KEY


def call_transport(call_context: Mapping[str, Any] | None) -> str | None:
    """Return what the call's transport stamped under ``TRANSPORT_KEY``, or ``None``."""
    if call_context is None:
        return None
    return call_context.get(TRANSPORT_KEY)
