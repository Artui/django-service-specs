from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.pool.base_pool import base_pool
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.types.progress_reporter import ProgressReporter
from django_service_specs.types.utils import CALL_CONTEXT


def seeded_pool(
    *,
    user: Any,
    seeds: PoolSeeds = DEFAULT_POOL_SEEDS,
    call_context: Mapping[str, Any],
    progress: ProgressReporter | None = None,
) -> dict[str, Any]:
    """The seeds of ``base_pool``, resolved under a call's context."""
    pool = base_pool(user=user, progress=progress, seeds=seeds, call_context=call_context)
    del pool[CALL_CONTEXT]
    return pool
