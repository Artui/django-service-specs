"""``is_deactivated``: the one rule every refusal of a deactivated principal reads."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from django_service_specs.authorization.utils import is_deactivated


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
