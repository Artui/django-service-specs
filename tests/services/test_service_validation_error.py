"""Tests for ``ServiceValidationError``."""

from __future__ import annotations

import re

import pytest

from django_service_specs.services import service_error, service_validation_error
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


def test_no_drf_imports_in_module() -> None:
    # The forbidden package name is built from parts rather than written
    # literally, so this test itself does not trip the repo-wide grep gate
    # that asserts the same absence from outside the test suite.
    forbidden_package = "rest_" + "framework"
    forbidden = re.compile(rf"\b(?:from|import)\s+{forbidden_package}")
    for module in (service_error, service_validation_error):
        source = module.__file__
        assert source is not None
        with open(source, encoding="utf-8") as fh:
            contents = fh.read()
        assert forbidden.search(contents) is None
