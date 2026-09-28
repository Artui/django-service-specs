"""Tests for ``ServiceValidationError``."""

from __future__ import annotations

import pytest

from django_service_specs.services.service_error import ServiceError
from django_service_specs.services.service_validation_error import ServiceValidationError


def test_string_detail() -> None:
    err = ServiceValidationError("bad input")
    assert err.detail == "bad input"
    assert err.message == "bad input"
    assert str(err) == "bad input"


def test_dict_detail() -> None:
    err = ServiceValidationError({"name": ["required"]})
    assert err.detail == {"name": ["required"]}
    assert err.message == ServiceValidationError.default_message


def test_list_detail() -> None:
    err = ServiceValidationError(["a", "b"])
    assert err.detail == ["a", "b"]
    assert err.message == ServiceValidationError.default_message


def test_inherits_from_service_error() -> None:
    with pytest.raises(ServiceError):
        raise ServiceValidationError("nope")
