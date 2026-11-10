from __future__ import annotations

from typing import NamedTuple


class ProviderKeys(NamedTuple):
    """What [`provider_keys`][django_service_specs.pool.provider_keys.provider_keys] read off a
    ``kwargs=`` provider, before it runs."""

    filled: frozenset[str]
    declinable: frozenset[str]
