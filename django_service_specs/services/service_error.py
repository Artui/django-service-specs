from __future__ import annotations

from django.utils.translation import gettext

from django_service_specs.types.utils import gettext_noop


class ServiceError(Exception):
    """Raised by services to signal a business-rule failure."""

    default_message: str = gettext_noop("Service error.")

    def __init__(self, message: str | None = None) -> None:
        self.message: str = message if message is not None else gettext(self.default_message)
        super().__init__(self.message)
