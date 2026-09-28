"""Tests for ``ServiceConflict``."""

from __future__ import annotations

import pytest

from django_service_specs.services.service_conflict import ServiceConflict
from django_service_specs.services.service_error import ServiceError


def test_default_message() -> None:
    err = ServiceConflict()
    assert err.message == "Conflict."


def test_custom_message() -> None:
    err = ServiceConflict("2024-01-01 at 10:00 is taken.")
    assert err.message == "2024-01-01 at 10:00 is taken."


def test_is_a_service_error() -> None:
    with pytest.raises(ServiceError):
        raise ServiceConflict()
