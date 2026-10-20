"""Tests for ``ServiceValidationError``."""

from __future__ import annotations

import copy
from typing import Any

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


@pytest.mark.parametrize("detail", [{"name": ["required"]}, ["a", "b"]], ids=["dict", "list"])
def test_structured_detail(detail: Any) -> None:
    # A copy, so a detail the error rewrote in place would not compare equal.
    err = ServiceValidationError(copy.deepcopy(detail))
    assert err.detail == detail
    assert err.message == ServiceValidationError.default_message


def test_inherits_from_service_error() -> None:
    with pytest.raises(ServiceError):
        raise ServiceValidationError("nope")
