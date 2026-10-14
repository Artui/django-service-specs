"""``is_deactivated``: the one rule every refusal of a deactivated principal reads."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from django_service_specs.authorization.utils import asked_with, is_deactivated


def _user(*, is_active: bool) -> Any:
    # Unsaved: the rule reads attributes, never the database.
    return get_user_model()(username="ada", is_active=is_active)


def test_a_deactivated_user_is_deactivated() -> None:
    assert is_deactivated(_user(is_active=False)) is True


def test_an_active_user_is_not_deactivated() -> None:
    # Without the ``not is_active`` half, every authenticated principal would be.
    assert is_deactivated(_user(is_active=True)) is False


def test_anonymous_is_not_deactivated() -> None:
    # ``AnonymousUser.is_active`` is false: without the ``is_authenticated`` half,
    # anonymous would be refused before its permission check could admit it.
    assert AnonymousUser().is_active is False
    assert is_deactivated(AnonymousUser()) is False


@pytest.mark.parametrize(
    ("principal", "expected"),
    [
        (SimpleNamespace(is_authenticated=True), False),
        (SimpleNamespace(is_active=False), True),
        (SimpleNamespace(), False),
        (None, False),
    ],
    ids=["no-is-active-reads-as-active", "no-is-authenticated-is-not-anonymous", "neither", "none"],
)
def test_a_principal_missing_either_attribute_reads_by_its_default(
    principal: Any, expected: bool
) -> None:
    assert is_deactivated(principal) is expected


class _Shapes:
    """One method per way a parameter named ``arguments`` can be declared, or not."""

    def keyword_only(self, principal: Any, spec: Any, *, arguments: Any = None) -> bool:
        return True

    def positional_or_keyword(self, principal: Any, spec: Any, arguments: Any = None) -> bool:
        return True

    def positional_only(self, principal: Any, spec: Any, arguments: Any = None, /) -> bool:
        return True

    def variadic(self, principal: Any, spec: Any, *arguments: Any) -> bool:
        return True

    def spread_under_the_name(self, principal: Any, spec: Any, **arguments: Any) -> bool:
        return True

    def spread(self, principal: Any, spec: Any, **kwargs: Any) -> bool:
        return True

    def undeclared(self, principal: Any, spec: Any) -> bool:
        return True


@pytest.mark.parametrize("method", ["keyword_only", "positional_or_keyword"])
def test_a_parameter_a_keyword_reaches_is_handed_the_arguments(method: str) -> None:
    handed = {"pk": 1}
    assert asked_with(_Shapes(), method, handed) == {"arguments": handed}


@pytest.mark.parametrize("method", ["spread", "undeclared"])
def test_a_method_that_names_no_arguments_is_handed_nothing(method: str) -> None:
    assert asked_with(_Shapes(), method, {"pk": 1}) == {}


@pytest.mark.parametrize("method", ["positional_only", "variadic", "spread_under_the_name"])
def test_a_parameter_named_arguments_that_no_keyword_reaches_is_handed_nothing(
    method: str,
) -> None:
    assert asked_with(_Shapes(), method, {"pk": 1}) == {}
