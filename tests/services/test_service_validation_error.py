"""Tests for ``ServiceValidationError``."""

from __future__ import annotations

import pytest
from django.utils.translation import gettext_lazy

from django_service_specs.services.service_error import ServiceError
from django_service_specs.services.service_validation_error import ServiceValidationError


def test_string_detail() -> None:
    err = ServiceValidationError("bad input")
    assert err.detail == "bad input"
    assert err.message == "bad input"
    assert str(err) == "bad input"


def test_lazy_detail() -> None:
    # A lazy string is not a ``str``, and read as one of the structured shapes
    # its text was replaced by the default message.
    detail = gettext_lazy("Pick another day.")
    err = ServiceValidationError(detail)
    assert err.message is detail
    assert str(err) == "Pick another day."


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
