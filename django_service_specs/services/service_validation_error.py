from __future__ import annotations

from typing import Any, cast

from django.utils.functional import Promise
from django.utils.translation import gettext

from django_service_specs.services.service_error import ServiceError
from django_service_specs.types.utils import gettext_noop


class ServiceValidationError(ServiceError):
    """Raised by services to signal invalid input or invalid state."""

    default_message: str = gettext_noop("Service validation error.")

    def __init__(self, detail: str | dict[str, Any] | list[Any]) -> None:
        # A lazy translation is one message: it is not a ``str``, but must not read as a list.
        message = (
            cast("str", detail)
            if isinstance(detail, str | Promise)
            else gettext(self.default_message)
        )
        super().__init__(message)
        self.detail: str | dict[str, Any] | list[Any] = detail
