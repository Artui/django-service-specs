from __future__ import annotations

from django_service_specs.selectors.run_selector import run_selector


def _sync_fn(*, value: int) -> int:
    return value * 2


async def _async_fn(*, value: int) -> int:
    return value * 3


def test_a_sync_selector_is_called() -> None:
    assert run_selector(_sync_fn, {"value": 5}) == 10


def test_an_async_selector_is_bridged() -> None:
    assert run_selector(_async_fn, {"value": 5}) == 15
