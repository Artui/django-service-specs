"""Generic service-layer error.

Framework-agnostic. A transport maps it to whatever shape it answers in.
"""

from __future__ import annotations

from django.utils.translation import gettext

from django_service_specs.types.utils import gettext_noop


class ServiceError(Exception):
    """Raised by services to signal a business-rule failure.

    Carries a ``message`` and nothing else, so a transport can surface it
    without the service depending on that transport. A structured payload
    belongs to a member that declares one:
    [`ServiceValidationError`][django_service_specs.services.service_validation_error.ServiceValidationError]
    carries a field-keyed ``detail``.

    ``default_message`` is a msgid in the package's catalog, as each member's
    is, and is looked up in the active language each time a refusal is built
    with no message of its own, so it reads in the language of the request
    that raised it. A ``message`` the caller passes is used as given.
    """

    default_message: str = gettext_noop("Service error.")

    def __init__(self, message: str | None = None) -> None:
        self.message: str = message if message is not None else gettext(self.default_message)
        super().__init__(self.message)
