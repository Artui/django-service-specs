from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.pool.reserved_pool_seeds import RESERVED_POOL_SEEDS
from django_service_specs.types.is_async import is_async
from django_service_specs.types.utils import SHAPES

# A single registration: ``(name, resolver)``. A tuple rather than a mapping so
# the registry stays frozen and the resolution order is the registration order,
# which is what makes an error message or a listing reproducible.
_Seed = tuple[str, Callable[..., Any]]

# What the refusal of a seed registered as ``shapes`` adds, for a project that
# registered the name before it was reserved. A seed is no parameter, so it
# cannot say "rename the parameter": it says where the call's shape values are
# read, and that the resolver needs a name of its own.
_SHAPES_SEED_HINT = (
    " 'shapes' is reserved for the seed holding the call's shape values by name, which a "
    "callable reads by declaring 'shapes'; register the resolver under a name of its own."
)


def _refuse_unusable_names(seeds: tuple[_Seed, ...]) -> None:
    """Refuse a registration naming a dispatcher-owned seed, or naming one twice."""
    seen: set[str] = set()
    for name, _ in seeds:
        if name in RESERVED_POOL_SEEDS:
            hint = _SHAPES_SEED_HINT if name == SHAPES else ""
            raise ValueError(
                f"{name!r} is a reserved pool seed carrying the dispatcher's own "
                f"value; registering it would shadow what the transport resolved. "
                f"Reserved: {sorted(RESERVED_POOL_SEEDS)}.{hint}"
            )
        if name in seen:
            raise ValueError(
                f"{name!r} is already registered on this PoolSeeds. Registering it "
                f"twice would make which resolver wins depend on registration order."
            )
        seen.add(name)


@dataclass(frozen=True)
class PoolSeeds:
    """Names a project adds to every dispatched callable's kwargs pool."""

    seeds: tuple[_Seed, ...] = ()

    def __post_init__(self) -> None:
        # Here, not in ``extend``: ``replace`` runs this too, and the class is public.
        _refuse_unusable_names(self.seeds)
        for name, resolver in self.seeds:
            if is_async(resolver) or inspect.isasyncgenfunction(resolver):
                label = getattr(resolver, "__qualname__", None) or type(resolver).__name__
                raise ImproperlyConfigured(
                    f"The pool seed {name!r} has an async resolver ({label}). A resolver "
                    "is called from sync code and never awaited, and its unawaited value "
                    "is truthy, so whatever reads the seed would read an answer nobody "
                    "computed; declare it with def."
                )

    def extend(self, **seeds: Callable[..., Any]) -> PoolSeeds:
        """Return a new registry with ``seeds`` appended."""
        return replace(self, seeds=self.seeds + tuple(seeds.items()))

    @property
    def names(self) -> frozenset[str]:
        """The registered names, without their resolvers."""
        return frozenset(name for name, _ in self.seeds)

    @property
    def reserved(self) -> frozenset[str]:
        """Every name an argument may not occupy: the dispatcher's plus these."""
        return RESERVED_POOL_SEEDS | self.names

    def resolvers(self) -> Mapping[str, Callable[..., Any]]:
        """The registrations as a mapping, for a caller that resolves them."""
        return dict(self.seeds)


DEFAULT_POOL_SEEDS: PoolSeeds = PoolSeeds()
"""The empty registry every dispatch entry point falls back to.

A project that registers nothing gets the pool dispatch builds on its own: the
principal as ``user``, a reporter as ``progress``, and each step's own values
(``data``, ``instance``, ``collection``, ``result``, ``queryset``) where that
step has them.
"""
