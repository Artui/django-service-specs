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
    """Return a new ``call_context`` for one call, stamped with ``transport``.

    The dict holds every entry of ``base`` and the four standard entries,
    ``request``, ``view``, ``format`` and ``action``, each ``None`` where
    neither ``base`` nor an argument gave one, so a stage reading
    ``call_context["action"]`` gets ``None`` rather than a ``KeyError`` on any
    transport that builds through this
    (test_every_standard_entry_is_there_and_none_where_nothing_gave_one).
    Dispatch hands a callable declaring ``request`` or ``view`` ``None`` for a
    ``None`` entry, exactly as for a missing one, so filling them changes no
    binding (test_with_every_standard_key_none_every_stage_is_handed_none).

    Each layer wins over the one before it: the ``None`` defaults, then
    ``base``, then each argument that is not ``None``, then ``transport``,
    written last so it replaces a ``transport`` entry ``base`` carried. An
    argument left at ``None`` is not given, so it leaves ``base``'s entry
    (test_a_none_argument_leaves_base_s_entry); to clear one, edit the result.

    ``base`` is copied, shallowly and never mutated: its values are the very
    objects it held, so a request is the request. The result is a plain ``dict``,
    a fresh one on every call and the caller's to keep: a transport that hands
    one dict to every callable of a request builds it once and passes the same
    object each time.
    """
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
