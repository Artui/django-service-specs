"""``server_owned_keys`` - the names a spec's dispatch fills that no caller supplies."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.pool.provider_keys import provider_keys
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec


def server_owned_keys(
    spec: ServiceSpec | SelectorSpec, *, pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS
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
      ``input_data`` and its target selector's ``kwargs``. A provider's values
      are merged after the caller's, so a key it fills holds the author's
      value whatever the caller sent.

    **Dispatch stops demanding a key only where the provider's values reach
    it**: a selector's ``kwargs`` relaxes that selector's reads, a service
    spec's ``kwargs`` its ``reads``, and ``input_data`` its Validator's
    parameters. A key one provider fills that another parameter declares - a
    read named by ``input_data``, a target selector's read or a Validator
    field named by the spec's ``kwargs``, a spec read named by the target
    selector's ``kwargs`` - is in this set and still required by dispatch.

    A key a provider may decline with ``UNSET`` is not here: the caller's
    value is the one the callable receives when it does. Nor is any key of a
    provider whose return says nothing about its keys, which may fill any name
    and so names none.

    djangorestframework-services' own reading adds the keys its reflected
    input markers hide, which this package does not read.
    """
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
