"""Tests for ``base_pool``."""

from __future__ import annotations

from typing import Any

import pytest

from django_service_specs.pool.base_pool import base_pool
from django_service_specs.pool.null_progress import null_progress
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS


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


def test_a_resolver_sees_the_caller_s_reporter() -> None:
    def reporter(progress: float, **_: Any) -> None: ...

    seeds = DEFAULT_POOL_SEEDS.extend(sink=lambda *, progress: progress)
    assert base_pool(user="u", progress=reporter, seeds=seeds)["sink"] is reporter
