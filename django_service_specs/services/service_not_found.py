from __future__ import annotations

from django_service_specs.services.service_error import ServiceError
from django_service_specs.types.utils import gettext_noop


class ServiceNotFound(ServiceError):
    """The operation's target does not exist, or is not this caller's to see."""

    default_message: str = gettext_noop("Not found.")
