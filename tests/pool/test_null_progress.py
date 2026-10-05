"""``null_progress``: the reporter a pool carries when the caller supplied none."""

from __future__ import annotations

from django_service_specs.pool.null_progress import null_progress
from django_service_specs.types.progress_reporter import ProgressReporter


def test_null_progress_discards_every_report_and_returns_none() -> None:
    assert null_progress(1) is None
    assert null_progress(2, total=4, message="half", meta={"com.example/stage": "rows"}) is None


def test_null_progress_is_a_progress_reporter() -> None:
    # Checked by the type checker rather than at runtime: the Protocol is not
    # ``runtime_checkable``, so this assignment is what holds the signatures together.
    reporter: ProgressReporter = null_progress
    assert reporter is null_progress
