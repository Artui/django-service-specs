"""``TRANSPORT_KEY`` - the key a call's context names its transport under."""

from __future__ import annotations

from typing import Final

TRANSPORT_KEY: Final = "transport"
"""The ``call_context`` key that names the transport which built the call's context.

The transport stamps it last, over anything already there, as the plain string,
so ``call_context["transport"] == "agent"`` holds with nothing imported. The kernel
neither writes nor reads it, and it is not a reserved name: a seed or an argument
may be called ``transport``. A missing key means an in-process caller, or a
transport on a release that has not adopted the key yet. See
[reading which transport is calling](dispatching.md#reading-which-transport-is-calling)."""
