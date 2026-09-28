"""Tests for ``ServiceError``."""

from __future__ import annotations

import pytest

from django_service_specs.services.service_error import ServiceError


def test_default_message() -> None:
    err = ServiceError()
    assert err.message == ServiceError.default_message
    assert str(err) == ServiceError.default_message


def test_custom_message() -> None:
    err = ServiceError("boom")
    assert err.message == "boom"
    assert str(err) == "boom"


def test_is_exception() -> None:
    with pytest.raises(ServiceError, match="x"):
        raise ServiceError("x")
