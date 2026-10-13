"""Tests for ``base_pool``."""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.pool.base_pool import base_pool
from django_service_specs.pool.null_progress import null_progress
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance


def test_seeds_are_the_documented_ones() -> None:
    user = object()
    assert base_pool(user=user) == {"user": user, "progress": null_progress}


def test_extra_entries_join_the_seeds() -> None:
    """An adapter can build its whole pool here instead of restating the seeds."""
    own_entries: dict[str, Any] = {"tenant": "acme", "trace_id": 7}
    pool = base_pool(user="u", **own_entries)
    assert pool == {"user": "u", "progress": null_progress, "tenant": "acme", "trace_id": 7}


def test_an_entry_named_user_collides_loudly() -> None:
    """The reason to route adapter entries through here rather than a dict literal.

    A literal would let the entry outrank the transport's authenticated value in
    silence; spreading it into this call cannot, because ``user`` is already a
    named parameter and Python itself refuses the duplicate.
    """
    own_entries: dict[str, Any] = {"user": "spoofed"}
    with pytest.raises(TypeError):
        base_pool(user="real", **own_entries)


def test_a_registered_seed_is_resolved_into_the_pool() -> None:
    seeds = DEFAULT_POOL_SEEDS.extend(tenant=lambda *, user: f"tenant-of-{user}")
    assert base_pool(user="u", seeds=seeds)["tenant"] == "tenant-of-u"


def test_a_resolver_receives_only_the_pool_entries_it_declares() -> None:
    """Seeds bind by the same declare-to-receive rule as every other spec callable."""
    seen: dict[str, Any] = {}

    def tenant_of(*, user: Any) -> str:
        seen["kwargs"] = {"user": user}
        return "acme"

    base_pool(user="u", seeds=DEFAULT_POOL_SEEDS.extend(tenant=tenant_of))
    assert seen == {"kwargs": {"user": "u"}}


def test_a_resolver_declaring_var_keyword_receives_the_whole_pool() -> None:
    captured: dict[str, Any] = {}

    def everything(**pool: Any) -> str:
        captured.update(pool)
        return "x"

    base_pool(user="u", seeds=DEFAULT_POOL_SEEDS.extend(seed=everything))
    assert set(captured) == {"user", "progress"}


def test_a_seed_cannot_read_another_seed() -> None:
    """Resolvers bind against the pool *before* any seed is written.

    Deliberate: it makes the result independent of registration order, so
    re-ordering two ``extend`` calls cannot silently change what a callable sees.
    A seed that needs another composes the two inside its own resolver.
    """

    def wants_a_sibling(**pool: Any) -> Any:
        return "tenant" in pool

    seeds = DEFAULT_POOL_SEEDS.extend(tenant=lambda: "acme").extend(saw=wants_a_sibling)
    assert base_pool(user="u", seeds=seeds)["saw"] is False


def test_a_seed_colliding_with_a_spread_entry_is_refused() -> None:
    """``**extra`` is per-call and a seed is ambient; one silently outranking the
    other is the ambiguity the registry exists to remove."""
    seeds = DEFAULT_POOL_SEEDS.extend(tenant=lambda: "registered")
    with pytest.raises(TypeError, match="tenant"):
        base_pool(user="u", seeds=seeds, tenant="spread")


def test_a_supplied_reporter_is_seeded_as_it_is() -> None:
    def reporter(progress: float, **_: Any) -> None: ...

    assert base_pool(user="u", progress=reporter)["progress"] is reporter


class _Recorder(list[float]):
    """A reporter that is falsy until its first report."""

    def __call__(self, progress: float, **_: Any) -> None:
        self.append(progress)


def test_a_falsy_reporter_is_seeded_as_it_is() -> None:
    recorder = _Recorder()

    assert base_pool(user="u", progress=recorder)["progress"] is recorder


def test_a_resolver_sees_the_caller_s_reporter() -> None:
    def reporter(progress: float, **_: Any) -> None: ...

    seeds = DEFAULT_POOL_SEEDS.extend(sink=lambda *, progress: progress)
    assert base_pool(user="u", progress=reporter, seeds=seeds)["sink"] is reporter


async def _books_open() -> bool:
    """Awaited, the books are closed. Called sync, a coroutine, which is truthy."""
    return False


async def _books_open_lazily() -> Any:
    yield False


class _NotACoroutine:
    """Awaitable through ``__await__`` alone: no ``close()`` to call on it."""

    def __await__(self) -> Any:
        yield
        return False


class TestAResolverAnsweringWithAnAwaitable:
    """A plain ``def`` handing back a coroutine looks sync until it answers.

    The registry cannot refuse it, so the value is refused where it is
    resolved, before it enters a pool. One shape per disjunct of the guard.
    """

    def test_a_coroutine_is_refused_and_closed(self) -> None:
        answer = _books_open()
        seeds = DEFAULT_POOL_SEEDS.extend(books_open=lambda: answer)
        with pytest.raises(ImproperlyConfigured) as refused:
            base_pool(user="u", seeds=seeds)
        assert str(refused.value).startswith(
            "The pool seed 'books_open' resolved to an awaitable (coroutine)"
        )
        # Closed, so nothing is left to warn that it was never awaited.
        assert inspect.getcoroutinestate(answer) == inspect.CORO_CLOSED

    def test_an_awaitable_that_is_not_a_coroutine_is_refused(self) -> None:
        seeds = DEFAULT_POOL_SEEDS.extend(books_open=lambda: _NotACoroutine())
        with pytest.raises(ImproperlyConfigured, match="resolved to an awaitable"):
            base_pool(user="u", seeds=seeds)

    def test_an_async_generator_is_refused(self) -> None:
        # Not awaitable, so ``isawaitable`` alone would seed it as it is.
        answer = _books_open_lazily()
        seeds = DEFAULT_POOL_SEEDS.extend(books_open=lambda: answer)
        with pytest.raises(ImproperlyConfigured, match="resolved to an awaitable"):
            base_pool(user="u", seeds=seeds)


@pytest.mark.django_db
class TestDispatchDoesNotRunOnAnAwaitableSeed:
    """End to end: the seed's coroutine would have read as met, and the service run.

    Each reader answers with a real ``bool`` or raises, so the refusal that
    lands can only be the seed's, never the guard on a condition's answer.
    """

    def test_through_an_affordance(self) -> None:
        ran: list[Any] = []

        def service() -> None:
            ran.append(True)

        spec = ServiceSpec(
            service=service,
            permissions=[Unrestricted()],
            affordances=[
                Affordance(
                    code="books_closed",
                    reason="The books are closed.",
                    when=lambda *, books_open: bool(books_open),
                )
            ],
        )
        seeds = DEFAULT_POOL_SEEDS.extend(books_open=lambda: _books_open())
        with pytest.raises(ImproperlyConfigured) as refused:
            dispatch(spec, principal=object(), arguments={}, pool_seeds=seeds)
        assert "resolved to an awaitable" in str(refused.value)
        assert "answered with an awaitable" not in str(refused.value)
        assert ran == []

    def test_through_a_precondition(self) -> None:
        ran: list[Any] = []

        def service() -> None:
            ran.append(True)

        def books_must_be_open(*, books_open: Any) -> None:
            if not books_open:
                raise ValueError("The books are closed.")

        spec = ServiceSpec(
            service=service, permissions=[Unrestricted()], preconditions=[books_must_be_open]
        )
        seeds = DEFAULT_POOL_SEEDS.extend(books_open=lambda: _books_open())
        with pytest.raises(ImproperlyConfigured, match="resolved to an awaitable"):
            dispatch(spec, principal=object(), arguments={}, pool_seeds=seeds)
        assert ran == []
