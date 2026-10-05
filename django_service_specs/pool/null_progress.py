"""``null_progress`` - the reporter a pool carries when nobody is listening."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def null_progress(
    progress: float,
    *,
    total: float | None = None,
    message: str | None = None,
    meta: Mapping[str, Any] | None = None,
) -> None:
    """The
    [`ProgressReporter`][django_service_specs.types.progress_reporter.ProgressReporter]
    a transport with nowhere to send progress uses.

    Seeded by [`base_pool`][django_service_specs.pool.base_pool.base_pool]
    whenever the caller supplied no reporter, which is every dispatch from a
    transport with no progress channel of its own, every HTTP request, and every
    test.

    **The default is what makes the seed usable.** Without it, a service
    declaring ``progress`` would work over one transport and raise a
    ``TypeError`` over the others, so nobody could declare it in code meant to
    be shared - which is the entire premise of writing a service once.
    Discarding the report is the honest behaviour for a caller that cannot
    forward it; refusing the call is not.
    """
    del progress, total, message, meta
