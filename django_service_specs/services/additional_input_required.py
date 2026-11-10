from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.services.service_error import ServiceError


class AdditionalInputRequired(ServiceError):
    """A service cannot proceed without a value it was not given."""

    def __init__(self, message: str, *, schema: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.schema: Mapping[str, Any] | None = schema
