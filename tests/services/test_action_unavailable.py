"""Tests for ``ActionUnavailable``."""

from __future__ import annotations

import pytest

from django_service_specs.services.action_unavailable import ActionUnavailable
from django_service_specs.services.service_conflict import ServiceConflict


def test_default_message() -> None:
    err = ActionUnavailable(code="order_shipped")
    assert err.message == "This action is not available right now."
    assert err.code == "order_shipped"


def test_custom_message() -> None:
    err = ActionUnavailable("A shipped order cannot be cancelled.", code="order_shipped")
    assert err.message == "A shipped order cannot be cancelled."
    assert str(err) == "A shipped order cannot be cancelled."


def test_code_is_required_and_keyword_only() -> None:
    with pytest.raises(TypeError):
        ActionUnavailable("Not now.")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        ActionUnavailable("Not now.", "order_shipped")  # type: ignore[misc]


def test_is_a_service_conflict() -> None:
    # So a transport that has never heard of it still answers a conflict.
    with pytest.raises(ServiceConflict):
        raise ActionUnavailable(code="order_shipped")
