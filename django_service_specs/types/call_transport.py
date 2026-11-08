"""``call_transport`` - which transport built a call's context, as it stamped it."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.types.transport_key import TRANSPORT_KEY


def call_transport(call_context: Mapping[str, Any] | None) -> str | None:
    """Return what the call's transport stamped under ``TRANSPORT_KEY``, or ``None``.

    ``None`` means no transport built this context: an in-process caller, whose
    dict has no such key, or a Validator's ``parameters()`` asked outside a call,
    which is handed no dict at all.

    The stamp comes back as it was written, a known value or a third-party
    transport's own string, so compare it to a
    [`Transport`][django_service_specs.types.transport.Transport] member.
    """
    if call_context is None:
        return None
    return call_context.get(TRANSPORT_KEY)
