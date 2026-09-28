"""``RESERVED_POOL_SEEDS`` - the keyword names dispatch owns."""

from __future__ import annotations

from typing import Final

RESERVED_POOL_SEEDS: Final[frozenset[str]] = frozenset(
    {"user", "data", "instance", "collection", "result", "queryset", "progress"}
)
"""The names dispatch seeds into a callable's keyword pool, which no argument may use.

``user`` is the principal, ``data`` the validated values, ``instance`` and
``collection`` the resolved target, ``result`` the service's return (in an
output selector's pool) and ``queryset`` what ``extend_queryset`` shapes. They
are the names ``djangorestframework-services`` seeds for the same values, so a
callable written for it runs under this kernel unchanged.

``progress`` has no value yet and is reserved anyway, so that seeding it later
is additive: reserving a name after a spec has declared a parameter by it would
break that spec.

A parameter declaring one of these names is refused, because a spread argument
must never be able to outrank the value dispatch seeded - a caller naming
itself ``user`` is the case that matters. ``request`` and ``view`` are not here:
they are an HTTP adapter's, and it registers them through ``PoolSeeds``, which
reserves them the same way.
"""
