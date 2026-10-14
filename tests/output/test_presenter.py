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
