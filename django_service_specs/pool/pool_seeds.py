"""``PoolSeeds`` — a project's own always-available kwargs-pool seeds."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from django_service_specs.pool.reserved_pool_seeds import RESERVED_POOL_SEEDS

# A single registration: ``(name, resolver)``. A tuple rather than a mapping so
# the registry stays frozen and the resolution order is the registration order,
# which is what makes an error message or a listing reproducible.
_Seed = tuple[str, Callable[..., Any]]


@dataclass(frozen=True)
class PoolSeeds:
    """Names a project adds to every dispatched callable's kwargs pool.

    The names in ``RESERVED_POOL_SEEDS`` are the dispatcher's own. Everything
    else a service legitimately needs — a tenant, a correlation id, a locale, a
    clock, a feature-flag reader — has no channel, because off HTTP there is no
    ``request`` for it to hang off. This is that channel.

    A registration contributes two things:

    - **the value**, resolved into every pool
      [`base_pool`][django_service_specs.pool.base_pool.base_pool] builds;
    - **reservation**: dispatch refuses a spec whose Parameters declare the
      name, and a Validator that returns a value under it, so an argument never
      meets a seed in one pool. A caller sending the name is then refused as an
      unknown argument, or dropped under ``UnknownArguments.IGNORE``, like any
      other name the spec does not declare.

    The reason the two travel together is that either alone is a trap. A seed
    with a value and no reservation shares the pool with an argument of the
    same name, and which of the two a callable receives would depend on
    spreading order; a reserved name with no value makes a callable that
    declares it fail with a ``TypeError`` instead.

    Immutable, and ``extend`` returns a **new** registry rather than mutating, so
    there is no shared global state to leak between mounts or across tests. Pass
    one per dispatch rather than installing it process-wide: a project that
    mounts two operations with different ambient context needs them to differ,
    and a module-level default cannot.

        seeds = DEFAULT_POOL_SEEDS.extend(tenant=lambda *, user: user.tenant)
        dispatch(spec, principal=user, arguments=arguments, pool_seeds=seeds)

    A resolver is called through the same declare-to-receive rule as every other
    spec callable: it names the pool entries it wants (``user``, an adapter's own
    entry) and receives only those, or takes ``**kwargs`` for all of them.

    Attributes:
        seeds: The registrations, in registration order.
    """

    seeds: tuple[_Seed, ...] = ()

    def extend(self, **seeds: Callable[..., Any]) -> PoolSeeds:
        """Return a new registry with ``seeds`` appended.

        Raises:
            ValueError: A name is one of the dispatcher's own, or is already
                registered here. Both are refused at **registration** rather
                than at dispatch, because a silent last-wins is the exact
                failure the reservation exists to prevent — and a collision
                discovered on the hot path is one a test suite can miss.
        """
        for name in seeds:
            if name in RESERVED_POOL_SEEDS:
                raise ValueError(
                    f"{name!r} is a reserved pool seed carrying the dispatcher's own "
                    f"value; registering it would shadow what the transport resolved. "
                    f"Reserved: {sorted(RESERVED_POOL_SEEDS)}."
                )
            if name in self.names:
                raise ValueError(
                    f"{name!r} is already registered on this PoolSeeds. Registering it "
                    f"twice would make which resolver wins depend on registration order."
                )
        return replace(self, seeds=self.seeds + tuple(seeds.items()))

    @property
    def names(self) -> frozenset[str]:
        """The registered names, without their resolvers."""
        return frozenset(name for name, _ in self.seeds)

    @property
    def reserved(self) -> frozenset[str]:
        """Every name an argument may not occupy: the dispatcher's plus these.

        Dispatch reads this rather than ``RESERVED_POOL_SEEDS`` directly, which
        is what makes a registered seed as protected as a built-in one.
        """
        return RESERVED_POOL_SEEDS | self.names

    def resolvers(self) -> Mapping[str, Callable[..., Any]]:
        """The registrations as a mapping, for a caller that resolves them.

        Resolution itself lives in
        [`base_pool`][django_service_specs.pool.base_pool.base_pool] rather
        than here: it needs the declare-to-receive helper
        (``resolve_callable_kwargs``), and this module stays a plain value
        carrier so nothing in ``pool/`` depends on it in a cycle.
        """
        return dict(self.seeds)


DEFAULT_POOL_SEEDS: PoolSeeds = PoolSeeds()
"""The empty registry every dispatch entry point falls back to.

A project that registers nothing gets exactly the behaviour that existed before
this type: the seven built-in seeds, and nothing else.
"""
