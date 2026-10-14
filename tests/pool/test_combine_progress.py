"""``combine_progress``: one report handed to every sink, each sink's failure its own."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.pool.combine_progress import combine_progress
from django_service_specs.pool.null_progress import null_progress
from django_service_specs.specs.service_spec import ServiceSpec
from tests.dispatch.utils import OPEN, make_user


def _recorder(into: list[tuple[Any, ...]]) -> Any:
    def report(
        progress: float,
        *,
        total: float | None = None,
        message: str | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> None:
        into.append((progress, total, message, meta))

    return report


def _boom(*_: Any, **__: Any) -> None:
    raise RuntimeError("The sink is down.")


def test_no_reporter_is_the_no_op_so_the_result_stays_callable() -> None:
    assert combine_progress() is null_progress
    assert combine_progress(None, None) is null_progress


def test_a_single_reporter_is_returned_unwrapped() -> None:
    only = _recorder([])

    assert combine_progress(None, only) is only


def test_every_argument_reaches_every_sink() -> None:
    first: list[tuple[Any, ...]] = []
    second: list[tuple[Any, ...]] = []

    combine_progress(_recorder(first), None, _recorder(second))(
        3, total=10, message="Halfway.", meta={"step": "copy"}
    )

    assert first == [(3, 10, "Halfway.", {"step": "copy"})]
    assert second == first


def test_a_failing_sink_does_not_silence_the_sinks_after_it() -> None:
    seen: list[tuple[Any, ...]] = []

    combine_progress(_boom, _recorder(seen))(1)

    assert seen == [(1, None, None, None)]


def test_a_failing_sink_never_reaches_the_caller() -> None:
    combine_progress(_boom, _boom)(1)


def test_sinks_hear_each_report_in_the_order_given() -> None:
    order: list[str] = []

    def first(*_: Any, **__: Any) -> None:
        order.append("first")

    def second(*_: Any, **__: Any) -> None:
        order.append("second")

    combine_progress(first, second)(1)

    assert order == ["first", "second"]


@pytest.mark.django_db
def test_a_service_reporting_through_dispatch_survives_a_failing_sink() -> None:
    """Handed to dispatch as ``progress=``, the combined reporter is what the service calls."""
    seen: list[tuple[Any, ...]] = []

    def service(*, progress: Any) -> str:
        progress(1, total=2)
        return "done"

    spec = ServiceSpec(service=service, permissions=OPEN)
    result = dispatch(
        spec,
        principal=make_user("ada"),
        arguments={},
        progress=combine_progress(_boom, _recorder(seen)),
    )

    assert result.value == "done"
    assert seen == [(1, 2, None, None)]


@pytest.mark.django_db
def test_dispatch_s_own_join_is_not_this_one_and_lets_a_failure_through() -> None:
    """A spec's ``progress_reporter`` sink failing reaches the service, as the docstring says."""

    def service(*, progress: Any) -> str:
        progress(1)
        return "done"

    spec = ServiceSpec(service=service, permissions=OPEN, progress_reporter=lambda: _boom)

    with pytest.raises(RuntimeError, match="The sink is down."):
        dispatch(spec, principal=make_user("ada"), arguments={}, progress=_recorder([]))
