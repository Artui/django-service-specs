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


def test_forwards_in_the_order_the_callable_declares() -> None:
    # The pool's own order is not the one kept: a caller reading the result as
    # a sequence sees the signature's.
    resolved = resolve_callable_kwargs(lambda *, b, a, c: None, {"a": 1, "c": 3, "b": 2})
    assert list(resolved) == ["b", "a", "c"]


class TestTheCallContextIsHandedByNameOnly:
    """``call_context`` reaches a callable naming it, never one taking ``**kwargs`` for the rest.

    A catch-all written before the name existed forwards what it gets, so one
    more key would break it on an upgrade it never asked for.
    """

    def test_a_catch_all_is_never_handed_it(self) -> None:
        context: dict[str, Any] = {}
        assert resolve_callable_kwargs(
            lambda **kwargs: kwargs, {"a": 1, "call_context": context}
        ) == {"a": 1}

    def test_a_catch_all_naming_it_is_handed_the_very_dict(self) -> None:
        context: dict[str, Any] = {}

        def fn(*, call_context: Any, **kwargs: Any) -> Any:
            return call_context, kwargs

        handed = resolve_callable_kwargs(fn, {"a": 1, "call_context": context})
        assert handed == {"a": 1, "call_context": context}
        assert handed["call_context"] is context

    def test_a_callable_naming_it_alone_is_handed_it(self) -> None:
        context: dict[str, Any] = {}
        handed = resolve_callable_kwargs(
            lambda *, call_context: call_context, {"a": 1, "call_context": context}
        )
        assert handed == {"call_context": context}
