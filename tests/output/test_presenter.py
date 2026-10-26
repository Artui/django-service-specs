from __future__ import annotations

from typing import Any

import pytest

from django_service_specs.output.output import Output
from django_service_specs.output.presenter import Presenter


def test_both_halves_are_required() -> None:
    class _OnlyPresents(Presenter):
        def present(self, value: Any) -> Any:
            return value

    with pytest.raises(TypeError, match="output"):
        _OnlyPresents()


def test_a_complete_presenter_instantiates() -> None:
    class _Identity(Presenter):
        def output(self) -> Output:
            return Output()

        def present(self, value: Any) -> Any:
            return value

    assert _Identity().present(1) == 1


def test_by_default_a_value_is_presented_whatever_the_call() -> None:
    """``presented()`` is what dispatch's ``present`` asks for; a presenter that
    reads nothing of the call overrides ``present()`` alone."""

    class _Doubling(Presenter):
        def output(self) -> Output:
            return Output()

        def present(self, value: Any) -> Any:
            return value * 2

    assert _Doubling().presented(2, None) == 4
    assert _Doubling().presented(3, object()) == 6


def test_by_default_a_list_is_each_of_its_rows_presented_with_the_one_context() -> None:
    """``presented_rows()`` is what dispatch's ``present`` asks for a list; a
    presenter that batches nothing overrides ``present()`` or ``presented()``."""

    class _Tagging(Presenter):
        def output(self) -> Output:
            return Output()

        def present(self, value: Any) -> Any:
            return value

        def presented(self, value: Any, context: Any) -> Any:
            return (value, context)

    context = object()

    assert _Tagging().presented_rows((1, 2), context) == [(1, context), (2, context)]
    assert _Tagging().presented_rows((), None) == []
