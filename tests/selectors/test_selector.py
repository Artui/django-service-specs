"""``Selector``: any callable, checked structurally."""

from __future__ import annotations

from typing import Any

from django_service_specs.selectors.selector import Selector


def _read(**_: Any) -> list[Any]:
    return []


async def _aread(**_: Any) -> list[Any]:
    return []


def test_any_callable_is_a_selector() -> None:
    assert isinstance(_read, Selector)
    assert isinstance(len, Selector)


def test_what_is_not_callable_is_not() -> None:
    assert not isinstance([], Selector)
    assert not isinstance(None, Selector)


def test_an_async_def_passes_too_so_the_check_cannot_tell_the_kinds_apart() -> None:
    assert isinstance(_aread, Selector)
