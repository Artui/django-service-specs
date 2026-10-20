"""Tests for ``is_async`` — the callable-kind predicate."""

from __future__ import annotations

import functools
from typing import Any

import pytest

from django_service_specs.types.is_async import is_async


class _AsyncCallable:
    async def __call__(self) -> str:
        return "async-callable"


class _SyncCallable:
    def __call__(self) -> str:
        return "sync-callable"


class _NoCall: ...


async def _async_fn() -> int:
    return 1


def _sync_fn() -> int:
    return 1


@pytest.mark.parametrize(
    ("fn", "expected"),
    [
        pytest.param(_async_fn, True, id="async-def"),
        pytest.param(_sync_fn, False, id="sync-def"),
        pytest.param(_AsyncCallable(), True, id="async-callable-class"),
        pytest.param(_SyncCallable(), False, id="sync-callable-class"),
        pytest.param(functools.partial(_async_fn), True, id="partial-of-async"),
        pytest.param(functools.partial(_sync_fn), False, id="partial-of-sync"),
        pytest.param(lambda: 1, False, id="lambda"),
        # Not callable at all, and still answered rather than raised on.
        pytest.param(_NoCall(), False, id="object-without-call"),
    ],
)
def test_is_async(fn: Any, expected: bool) -> None:
    assert is_async(fn) is expected
