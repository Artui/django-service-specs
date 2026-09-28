"""Generic service-layer error.

Framework-agnostic. A transport maps it to whatever shape it answers in.
"""

from __future__ import annotations


class ServiceError(Exception):
    """Raised by services to signal a business-rule failure.

    Carries a ``message`` and nothing else, so a transport can surface it
    without the service depending on that transport. A structured payload
    belongs to a member that declares one:
    [`ServiceValidationError`][django_service_specs.services.service_validation_error.ServiceValidationError]
    carries a field-keyed ``detail``.
    """

    default_message: str = "Service error."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message if message is not None else self.default_message)
        self.message: str = message if message is not None else self.default_message
