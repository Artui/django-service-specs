"""Tests for ``AdditionalInputRequired``."""

from __future__ import annotations

import pytest

from django_service_specs.services.additional_input_required import AdditionalInputRequired
from django_service_specs.services.service_conflict import ServiceConflict
from django_service_specs.services.service_error import ServiceError
from django_service_specs.services.service_validation_error import ServiceValidationError


def test_message_and_no_schema() -> None:
    err = AdditionalInputRequired("120 rows match. Confirm to proceed.")
    assert err.message == "120 rows match. Confirm to proceed."
    assert err.schema is None


def test_schema_is_kept_as_given() -> None:
    schema = {"confirmed": {"type": "boolean"}}
    err = AdditionalInputRequired("Confirm to proceed.", schema=schema)
    assert err.schema is schema


def test_schema_is_keyword_only() -> None:
    with pytest.raises(TypeError):
        AdditionalInputRequired("Confirm.", {"confirmed": {}})  # type: ignore[misc]


def test_is_a_plain_service_error() -> None:
    # Not a validation error: what was sent is not wrong. Not a conflict
    # either: nothing about the resource's state needs re-reading.
    err = AdditionalInputRequired("Confirm.")
    assert isinstance(err, ServiceError)
    assert not isinstance(err, ServiceValidationError | ServiceConflict)
