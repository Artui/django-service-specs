"""Validation error raised from service code."""

from __future__ import annotations

from typing import Any, cast

from django.utils.functional import Promise

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
        # A lazy translation is one message, as a string is, though it is not a
        # ``str``: read as a mapping or a list would be, its text gave way to
        # the default. It stays lazy, so it renders in the language active
        # where it is answered rather than where it was raised. Each half is
        # held by its own test: test_string_detail and test_lazy_detail.
        message = cast("str", detail) if isinstance(detail, str | Promise) else self.default_message
        super().__init__(message)
        self.detail: str | dict[str, Any] | list[Any] = detail
