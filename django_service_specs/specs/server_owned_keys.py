"""``server_owned_keys`` - the names a spec's dispatch fills that no caller supplies."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.pool.provider_keys import provider_keys
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource, kernel_spec


def server_owned_keys(
    spec: ServiceSpec | SelectorSpec | SpecSource, *, pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS
) -> frozenset[str]:
    """Every name ``spec``'s dispatch fills from the server, whatever the caller sends.

    For a transport building an input schema of its own, beside the one
    ``parameters()`` describes: subtract this set from what it lists, so it
    asks the caller for no key the server answers anyway. The union of:

    - the names the pool seeds carry: the dispatcher's own (``user``,
      ``data``, ``instance`` and the rest) and every seed ``pool_seeds``
      registers, which no parameter may be named after;
    - the keys each provider the dispatch runs is annotated to fill, as
      [`provider_keys`][django_service_specs.pool.provider_keys.provider_keys]
      reads them: the spec's ``kwargs`` and, on a service spec, its
      ``input_data`` and its target selector's ``kwargs``. Dispatch drops the
      caller's value for a key a provider fills once it has been checked, so
      the key holds the author's value whatever the caller sent, or nothing
      at all when the provider leaves it out or returns ``UNSET``.

    **No name here is a parameter dispatch demands of the caller**, so a key
    a provider fills is the server's for the whole call. Each provider's
    values reach one seat - a selector's ``kwargs`` that selector's reads, a
    service spec's ``kwargs`` its ``reads``, ``input_data`` its Validator's
    fields - and dispatch does not demand a parameter there that the provider
    fills. A filled key that a parameter in any other seat declares is
    refused when the spec is built, or, for a Validator field, when
    ``parameters()`` is assembled. A key no parameter declares is the server's
    alone.

    A key a provider may decline with ``UNSET`` is not here: the caller's
    value is the one the callable receives when it does. Nor is any key of a
    provider whose return says nothing about its keys, which may fill any name
    and so names none.

    A [`SpecSource`][django_service_specs.specs.spec_source.SpecSource] owns
    what the spec it compiles to owns. djangorestframework-services' own
    reading adds the keys its reflected
    input markers hide, which this package does not read.
    """
    spec = kernel_spec(spec)
    owned: set[str] = set(pool_seeds.reserved)
    providers: list[Callable[..., Any] | None] = [spec.kwargs]
    if isinstance(spec, ServiceSpec):
        target = spec.target_selector_spec()
        providers += [spec.input_data, None if target is None else target.kwargs]
    for provider in providers:
        keys = provider_keys(provider)
        if keys is not None:
            owned |= keys.filled
    return frozenset(owned)
