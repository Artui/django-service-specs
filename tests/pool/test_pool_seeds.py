"""Tests for ``PoolSeeds``."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.pool.call_seeds import CALL_SEEDS
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.pool.reserved_pool_seeds import RESERVED_POOL_SEEDS


def test_the_default_registry_is_empty() -> None:
    """So a project that registers nothing behaves exactly as before."""
    assert DEFAULT_POOL_SEEDS.names == frozenset()
    assert DEFAULT_POOL_SEEDS.reserved == RESERVED_POOL_SEEDS


def test_extend_returns_a_new_registry_and_leaves_the_original_alone() -> None:
    """No shared global state to leak across mounts or tests."""
    extended = DEFAULT_POOL_SEEDS.extend(tenant=lambda: "acme")
    assert extended.names == frozenset({"tenant"})
    assert DEFAULT_POOL_SEEDS.names == frozenset()
    assert extended is not DEFAULT_POOL_SEEDS


def test_a_registered_name_joins_the_reserved_set() -> None:
    """The whole point: a registered seed gets the protection the built-ins get."""
    extended = DEFAULT_POOL_SEEDS.extend(tenant=lambda: "acme")
    assert extended.reserved == RESERVED_POOL_SEEDS | {"tenant"}


def test_registering_a_built_in_name_is_refused() -> None:
    """A seed named ``user`` would shadow the value the transport authenticated."""
    with pytest.raises(ValueError, match="user"):
        DEFAULT_POOL_SEEDS.extend(user=lambda: "nope")


def test_registering_the_same_name_twice_is_refused() -> None:
    """Silent last-wins here reproduces the bug the reservation exists to prevent."""
    once = DEFAULT_POOL_SEEDS.extend(tenant=lambda: "acme")
    with pytest.raises(ValueError, match="tenant"):
        once.extend(tenant=lambda: "other")


def _tenant() -> str:
    return "acme"


def test_constructing_a_seed_named_shapes_is_refused_with_the_rename() -> None:
    """The dataclass is public: building it directly is no way round the reservation."""
    with pytest.raises(ValueError, match="reserved for the seed") as refused:
        PoolSeeds(seeds=(("shapes", _tenant),))
    assert "register the resolver under a name of its own" in str(refused.value)


@pytest.mark.parametrize("name", ["call_context", "user"])
def test_constructing_with_a_reserved_name_is_refused(name: str) -> None:
    """Only ``shapes`` carries the rename hint, on this path as on ``extend``."""
    with pytest.raises(ValueError, match=f"'{name}' is a reserved pool seed") as refused:
        PoolSeeds(seeds=(("tenant", _tenant), (name, _tenant)))
    assert "reserved for the seed" not in str(refused.value)


def test_constructing_with_a_name_twice_is_refused() -> None:
    with pytest.raises(ValueError, match="'tenant' is already registered on this PoolSeeds"):
        PoolSeeds(seeds=(("tenant", _tenant), ("tenant", _tenant)))


def test_a_reserved_name_is_refused_before_an_async_resolver() -> None:
    """The name is the first refusal on both paths: ``ValueError``, not ``ImproperlyConfigured``."""
    with pytest.raises(ValueError, match="reserved pool seed"):
        DEFAULT_POOL_SEEDS.extend(shapes=_books_open)
    with pytest.raises(ValueError, match="reserved pool seed"):
        PoolSeeds(seeds=(("shapes", _books_open),))
    # Two entries, the async resolver first: a loop that checked each entry's name
    # and then that entry's resolver would meet the async one before the reserved name.
    with pytest.raises(ValueError, match="reserved pool seed"):
        DEFAULT_POOL_SEEDS.extend(tenant=_books_open, user=_tenant)
    with pytest.raises(ValueError, match="reserved pool seed"):
        PoolSeeds(seeds=(("tenant", _books_open), ("shapes", _tenant)))


def test_resolvers_are_exposed_in_registration_order() -> None:
    """Stable order, so an error message or a listing is reproducible."""
    extended = PoolSeeds().extend(a=lambda: 1).extend(b=lambda: 2)
    assert list(extended.resolvers()) == ["a", "b"]


def test_resolvers_round_trips_the_registered_callable() -> None:
    def tenant_of(*, user: Any) -> str:
        return f"tenant-of-{user}"

    extended = DEFAULT_POOL_SEEDS.extend(tenant=tenant_of)
    assert extended.resolvers() == {"tenant": tenant_of}


async def _books_open() -> bool:
    return False


async def _books_open_lazily() -> Any:
    yield False


class _BooksOpen:
    """A callable object whose ``__call__`` is ``async def``: the object itself is not."""

    async def __call__(self) -> bool:
        return False


class TestAnAsyncResolverIsRefused:
    """A resolver is called from sync code and never awaited: an async one is refused.

    Its value would be a coroutine, which is truthy, so a condition or a
    precondition reading the seed would see an answer nobody computed. One
    shape per disjunct of the guard.
    """

    def test_an_async_def_is_refused(self) -> None:
        with pytest.raises(ImproperlyConfigured) as refused:
            DEFAULT_POOL_SEEDS.extend(books_open=_books_open)
        message = str(refused.value)
        assert message.startswith("The pool seed 'books_open' has an async resolver")
        assert "_books_open" in message

    def test_an_object_whose_call_is_async_is_refused(self) -> None:
        with pytest.raises(ImproperlyConfigured, match="has an async resolver"):
            DEFAULT_POOL_SEEDS.extend(books_open=_BooksOpen())

    def test_an_async_generator_function_is_refused(self) -> None:
        with pytest.raises(ImproperlyConfigured, match="has an async resolver"):
            DEFAULT_POOL_SEEDS.extend(books_open=_books_open_lazily)

    def test_constructing_the_registry_directly_is_refused_too(self) -> None:
        # ``extend`` is not the only door: the dataclass is public.
        with pytest.raises(ImproperlyConfigured, match="has an async resolver"):
            PoolSeeds(seeds=(("books_open", _books_open),))


def test_reserved_keeps_its_published_answer_without_the_call_s_names() -> None:
    """The transports drop or refuse a caller's argument by ``reserved``; dispatch refuses the rest.

    djangorestframework-services drops a caller's argument named in ``reserved``,
    so widening it would drop a caller's ``view`` where that transport refuses it.
    """
    assert PoolSeeds().reserved == RESERVED_POOL_SEEDS
    assert not CALL_SEEDS & PoolSeeds().reserved


def test_extend_registers_request_and_view_as_a_released_transport_does() -> None:
    """Refusing either would refuse django-spec-agents' registration on every call."""
    seeds = DEFAULT_POOL_SEEDS.extend(request=lambda: "r", view=lambda: "v")
    assert seeds.names == {"request", "view"}
