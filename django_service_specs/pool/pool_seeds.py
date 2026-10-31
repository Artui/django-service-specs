"""``PoolSeeds`` — a project's own always-available kwargs-pool seeds."""

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
    """Refuse a registration naming a dispatcher-owned seed, or naming one twice.

    Called from ``PoolSeeds.__post_init__``, which ``extend`` reaches through
    ``replace``, so a registry built directly is refused the same way as one
    extended. Each condition is held on both paths, in tests/pool/: the reserved
    check by ``test_registering_a_built_in_name_is_refused`` (extend) and
    ``test_constructing_with_a_reserved_name_is_refused`` (direct), the duplicate
    one by ``test_registering_the_same_name_twice_is_refused`` and
    ``test_constructing_with_a_name_twice_is_refused``. The ``shapes`` hint is
    conditional: ``test_a_seed_named_shapes_is_refused_with_the_rename`` and
    ``test_constructing_a_seed_named_shapes_is_refused_with_the_rename`` fail
    without it, and ``test_a_parameter_named_call_context_is_refused_without_the_shapes_rename``
    and ``test_constructing_with_a_reserved_name_is_refused`` fail if every
    refusal carries it.
    """
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
    """Names a project adds to every dispatched callable's kwargs pool.

    The names in ``RESERVED_POOL_SEEDS`` are the dispatcher's own. Everything
    else a service legitimately needs — a tenant, a correlation id, a locale, a
    clock, a feature-flag reader — has no channel, because off HTTP there is no
    ``request`` for it to hang off. This is that channel. Where there is one,
    a resolver declaring ``request`` reads it (``CALL_SEEDS``), and a
    transport may still register ``request`` or ``view`` itself, as the ones
    released before dispatch supplied them do; such a mount keeps its own.

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

    **A reserved name, or one registered twice, is refused with ``ValueError``**
    whichever way the registry is built: ``extend`` and the constructor run the
    same check, so a registry written out as ``PoolSeeds(seeds=(...,))`` cannot
    shadow the dispatcher's own value either.

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

    **A resolver is sync-only.** A seed is a resolver - a callable whose
    return is the value - and resolvers are called from sync code and never
    awaited. An ``async def``
    one would seed a coroutine, which is truthy, so an affordance condition or
    a precondition reading the seed would read an answer nobody computed. One
    is refused when the registry is built, with ``ImproperlyConfigured``; a
    plain ``def`` handing back an awaitable is refused where it is resolved,
    by ``base_pool``.

    Attributes:
        seeds: The registrations, in registration order.
    """

    seeds: tuple[_Seed, ...] = ()

    def __post_init__(self) -> None:
        # Here rather than in ``extend``, because ``extend`` builds its registry
        # through ``replace``, which runs this too, and the dataclass is public:
        # a registry constructed directly is refused the same way. The names are
        # all checked before any resolver is, so a reserved name holding an async
        # resolver raises the ``ValueError`` ``extend`` always raised, not the
        # ``ImproperlyConfigured``: ``test_a_reserved_name_is_refused_before_an_async_resolver``
        # fails without that order, on both paths. Three
        # disjuncts between ``is_async`` and this line, each held in
        # tests/pool/test_pool_seeds.py's ``TestAnAsyncResolverIsRefused``:
        # ``test_an_async_def_is_refused`` fails without the coroutine-function
        # check, ``test_an_object_whose_call_is_async_is_refused`` without the
        # class-level ``__call__`` one, and
        # ``test_an_async_generator_function_is_refused`` without the third.
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
        """Return a new registry with ``seeds`` appended.

        Raises:
            ImproperlyConfigured: A resolver is async - an ``async def``, an
                object whose ``__call__`` is one, or an async generator
                function. A resolver is never awaited.
            ValueError: A name is one of the dispatcher's own, or is already
                registered here (the same holds for a registry built directly:
                a name reserved, or given twice in ``seeds``). Both are refused
                at **registration** rather than at dispatch, because a silent
                last-wins is the exact failure the reservation exists to prevent
                — and a collision discovered on the hot path is one a test suite
                can miss.
        """
        # The names are checked by ``__post_init__``, which ``replace`` runs on
        # the combined tuple: a name already registered is a duplicate there.
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

A project that registers nothing gets the pool dispatch builds on its own: the
principal as ``user``, a reporter as ``progress``, and each step's own values
(``data``, ``instance``, ``collection``, ``result``, ``queryset``) where that
step has them.
"""
