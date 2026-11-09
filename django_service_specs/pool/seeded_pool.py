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
    """The seeds of [`base_pool`][django_service_specs.pool.base_pool.base_pool], resolved under a call's context.

    **A transport with a call context builds its pool here**, rather than
    spreading its own ``request`` beside a registered seed: ``base_pool`` refuses
    that pair, and it should, since a seed cannot silently outrank what the caller
    spread in. Here nothing is spread. A resolver declaring ``request`` or ``view``
    reads the context's, and a seed registered under either name is the value.

    ``call_context`` is what the resolvers bind against and no entry of what comes
    back: it is no seed, and a Validator's ``ambient`` is a pool built here. A
    transport that binds a callable against the context adds it back by name.
    ``user``, ``seeds`` and ``progress`` are as ``base_pool`` takes them.
    """
    pool = base_pool(user=user, progress=progress, seeds=seeds, call_context=call_context)
    del pool[CALL_CONTEXT]
    return pool
