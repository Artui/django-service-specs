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
