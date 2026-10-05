"""``RESERVED_POOL_SEEDS`` - the keyword names dispatch owns."""

from __future__ import annotations

from typing import Final

RESERVED_POOL_SEEDS: Final[frozenset[str]] = frozenset(
    {"user", "data", "instance", "collection", "result", "queryset", "progress"}
)
"""The names dispatch seeds into a callable's keyword pool, which no argument may use.

``user`` is the principal, ``progress`` the caller's progress reporter,
``data`` the validated values, ``instance`` and ``collection`` the resolved
target, ``result`` the service's return (in an output selector's pool) and
``queryset`` what ``extend_queryset`` shapes. They are the names
``djangorestframework-services`` seeds for the same values, so a callable
written for it runs under this kernel unchanged.

``progress`` is in every pool, and live only where there is work to report on:
a service's run, and a selector spec's own selector. In a target or output
selector's pool it is ``null_progress``, because a lookup has nothing to
report, and one reporting after the service finished would read to a watching
client as the work restarting. It was reserved before it carried a value, so
that seeding it was additive rather than a break for a spec that had declared
a parameter by it.

A parameter declaring one of these names is refused, because a spread argument
must never be able to outrank the value dispatch seeded - a caller naming
itself ``user`` is the case that matters. ``request`` and ``view`` are not here:
they are an HTTP adapter's, and it registers them through ``PoolSeeds``, which
reserves them the same way.
"""
