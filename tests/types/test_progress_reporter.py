"""``ProgressReporter``: the shape every reporter a dispatch hands over has."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.types.progress_reporter import ProgressReporter


class _Keeper:
    def __init__(self) -> None:
        self.reports: list[tuple[float, float | None, str | None, Any]] = []

    def __call__(
        self,
        progress: float,
        *,
        total: float | None = None,
        message: str | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> None:
        self.reports.append((progress, total, message, meta))


def test_any_callable_of_the_shape_is_a_reporter() -> None:
    # Structural: a transport's own sink satisfies the Protocol without
    # subclassing it, which is what lets a transport pass its reporter as it is.
    keeper = _Keeper()
    reporter: ProgressReporter = keeper

    reporter(1, total=2, message="half", meta={"com.example/stage": "rows"})
    reporter(2)

    assert keeper.reports == [(1, 2, "half", {"com.example/stage": "rows"}), (2, None, None, None)]
