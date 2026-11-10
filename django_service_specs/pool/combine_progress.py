from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.pool.null_progress import null_progress
from django_service_specs.types.progress_reporter import ProgressReporter


def combine_progress(*reporters: ProgressReporter | None) -> ProgressReporter:
    """One ``ProgressReporter`` forwarding to all of ``reporters``."""
    sinks: tuple[ProgressReporter, ...] = tuple(r for r in reporters if r is not None)
    if not sinks:
        return null_progress
    if len(sinks) == 1:
        return sinks[0]

    def report(
        progress: float,
        *,
        total: float | None = None,
        message: str | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> None:
        # A sink's failure is its own: later sinks still hear the report.
        for sink in sinks:
            try:
                sink(progress, total=total, message=message, meta=meta)
            except Exception:
                continue

    return report
