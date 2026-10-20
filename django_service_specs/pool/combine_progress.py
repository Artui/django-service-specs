"""``combine_progress`` - one progress report handed to several reporters."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.pool.null_progress import null_progress
from django_service_specs.types.progress_reporter import ProgressReporter


def combine_progress(*reporters: ProgressReporter | None) -> ProgressReporter:
    """One [`ProgressReporter`][django_service_specs.types.progress_reporter.ProgressReporter] forwarding to all of ``reporters``.

    For a transport with more than one sink of its own to hand dispatch's
    ``progress=``: the channel back to its client - MCP notifications, a
    websocket - beside a task record, an audit trail or metrics. Neither
    displaces the other; each report reaches every sink, in the order given.

    **Each sink is isolated.** A sink that raises neither skips the sinks after
    it nor reaches the service that reported, because telemetry failing must
    not take down the run it describes. The failure is swallowed, not logged: a
    sink that cares about its own errors handles them inside itself, where the
    context to act on them is. No sink may depend on the order, since none can
    observe whether an earlier one succeeded.

    This is not how dispatch joins a spec's own ``progress_reporter`` to the
    transport's reporter: there, a sink's failure reaches the service, as the
    transport's own reporter failing does.

    Args:
        *reporters: The sinks, in call order. ``None`` is dropped, so an
            optional reporter can be passed straight through.

    Returns:
        [`null_progress`][django_service_specs.pool.null_progress.null_progress]
        when no sink is left, so the result is always callable; the one sink
        itself, unwrapped, when one is left; otherwise a reporter handing each
        report to every sink.
    """
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
        for sink in sinks:
            try:
                sink(progress, total=total, message=message, meta=meta)
            except Exception:
                # A sink's failure is its own: the sinks after it still hear the
                # report, and the service that reported never sees it.
                continue

    return report
