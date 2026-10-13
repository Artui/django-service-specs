from __future__ import annotations

import inspect

from django_service_specs.selectors.arun_selector import arun_selector


def _sync_fn(*, value: int) -> int:
    return value * 2


async def _async_fn(*, value: int) -> int:
    return value * 3


async def test_an_async_selector_is_awaited() -> None:
    assert await arun_selector(_async_fn, {"value": 5}) == 15


async def test_a_sync_selector_is_called_inline() -> None:
    result = arun_selector(_sync_fn, {"value": 5})
    assert inspect.isawaitable(result)
    assert await result == 10
