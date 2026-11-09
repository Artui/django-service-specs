"""``call_transport`` - which transport built a call's context, as it stamped it."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.types.transport_key import TRANSPORT_KEY


def call_transport(call_context: Mapping[str, Any] | None) -> str | None:
    """Return what the call's transport stamped under ``TRANSPORT_KEY``, or ``None``.

    ``None`` means nothing stamped this context: an in-process caller, whose dict
    has no such key, a transport on a release that has not adopted the key yet, or
    a Validator's ``parameters()`` asked outside a call, which is handed no dict at
    all, unless a transport describing a spec hands a stamped dict with no call
    under way.

    The stamp comes back as it was written, whatever string the transport chose,
    so compare it to a plain string: ``call_transport(call_context) == "rest"``.
    """
    if call_context is None:
        return None
    return call_context.get(TRANSPORT_KEY)
