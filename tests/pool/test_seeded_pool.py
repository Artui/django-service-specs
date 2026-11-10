from __future__ import annotations

from typing import Any

import pytest

from django_service_specs.pool.base_pool import base_pool
from django_service_specs.pool.null_progress import null_progress
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS
from django_service_specs.pool.seeded_pool import seeded_pool
from django_service_specs.types.utils import CALL_CONTEXT


def test_a_registered_request_seed_resolves_from_the_call_context() -> None:
    request = object()
    seeds = DEFAULT_POOL_SEEDS.extend(request=lambda *, request: ("seeded", request))
    pool = seeded_pool(user="u", seeds=seeds, call_context={"request": request})
    assert pool["request"] == ("seeded", request)
    assert CALL_CONTEXT not in pool


def test_a_resolver_reads_the_context_s_request_and_view() -> None:
    request = object()
    seeds = DEFAULT_POOL_SEEDS.extend(tenant=lambda *, request, view: (request, view))
    pool = seeded_pool(user="u", seeds=seeds, call_context={"request": request})
    assert pool["tenant"] == (request, None)
    # Named, each is handed over; neither is a pool entry unless registered.
    assert pool == {"user": "u", "progress": null_progress, "tenant": (request, None)}


def test_the_pool_is_base_pool_s_with_no_seeds_registered() -> None:
    assert seeded_pool(user="u", call_context={"request": object()}) == base_pool(user="u")


def test_a_catch_all_resolver_is_never_handed_the_context() -> None:
    seeds = DEFAULT_POOL_SEEDS.extend(seen=lambda **kwargs: sorted(kwargs))
    assert seeded_pool(user="u", seeds=seeds, call_context={})["seen"] == ["progress", "user"]


def test_progress_passes_through() -> None:
    def reporter(progress: float, *, total: float | None = None, **meta: Any) -> None: ...

    seeds = DEFAULT_POOL_SEEDS.extend(saw=lambda *, progress: progress)
    pool = seeded_pool(user="u", seeds=seeds, call_context={}, progress=reporter)
    assert pool["progress"] is reporter
    assert pool["saw"] is reporter


def test_progress_defaults_to_the_no_op_reporter() -> None:
    assert seeded_pool(user="u", call_context={})["progress"] is null_progress


def test_a_seed_beside_a_spread_entry_still_raises_from_base_pool() -> None:
    # The refusal this exists to stay clear of, not one it lifts.
    request = object()
    seeds = DEFAULT_POOL_SEEDS.extend(request=lambda: "registered")
    with pytest.raises(TypeError, match="'request'"):
        base_pool(user="u", seeds=seeds, request=request, call_context={"request": request})
    assert seeded_pool(user="u", seeds=seeds, call_context={"request": request})["request"] == (
        "registered"
    )
