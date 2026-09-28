"""Validation error raised from service code."""

from __future__ import annotations

from typing import Any

from django_service_specs.services.service_error import ServiceError


class ServiceValidationError(ServiceError):
    """Raised by services to signal invalid input or invalid state.

    Distinct from
    [`ServiceError`][django_service_specs.services.service_error.ServiceError] so
    a transport can tell "the arguments were fine but the business rule refused"
    from "the input itself is invalid" and map the two differently. ``detail``
    may be a string, a dict (field → error(s)), or a list of errors."""

    default_message: str = "Service validation error."

    def __init__(self, detail: str | dict[str, Any] | list[Any]) -> None:
        message: str = detail if isinstance(detail, str) else self.default_message
        super().__init__(message)
        self.detail: str | dict[str, Any] | list[Any] = detail
