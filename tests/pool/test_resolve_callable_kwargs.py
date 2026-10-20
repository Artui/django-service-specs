"""Tests for ``resolve_callable_kwargs`` — the declare-to-receive binder."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from django_service_specs.pool.resolve_callable_kwargs import resolve_callable_kwargs


@pytest.mark.parametrize(
    ("fn", "pool", "expected"),
    [
        pytest.param(
            lambda *, a, b: a + b, {"a": 1, "b": 2, "c": 3}, {"a": 1, "b": 2}, id="keyword-only"
        ),
        pytest.param(lambda **kwargs: kwargs, {"a": 1, "b": 2}, {"a": 1, "b": 2}, id="var-keyword"),
        pytest.param(lambda *, a, b=0: a + b, {"a": 1}, {"a": 1}, id="a-key-the-pool-lacks"),
        pytest.param(
            lambda a, b: a + b,
            {"a": 1, "b": 2, "c": 3},
            {"a": 1, "b": 2},
            id="positional-or-keyword",
        ),
        # *args is VAR_POSITIONAL, not collected as a kwarg.
        pytest.param(lambda *args, b: b, {"args": (1, 2), "b": 3}, {"b": 3}, id="var-positional"),
    ],
)
def test_forwards_what_the_callable_declares(
    fn: Callable[..., Any], pool: dict[str, Any], expected: dict[str, Any]
) -> None:
    assert resolve_callable_kwargs(fn, pool) == expected
