"""Tests for ``PoolSeeds``."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

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
