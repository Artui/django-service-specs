"""Tests for ``ServiceNotFound``."""

from __future__ import annotations

import pytest

from django_service_specs.services.service_error import ServiceError
from django_service_specs.services.service_not_found import ServiceNotFound


def test_default_message() -> None:
    err = ServiceNotFound()
    assert err.message == "Not found."


def test_custom_message() -> None:
    err = ServiceNotFound("No event 7.")
    assert err.message == "No event 7."


def test_is_a_service_error() -> None:
    with pytest.raises(ServiceError):
        raise ServiceNotFound()
