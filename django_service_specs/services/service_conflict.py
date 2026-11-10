from __future__ import annotations

from django_service_specs.services.service_error import ServiceError
from django_service_specs.types.utils import gettext_noop


class ServiceConflict(ServiceError):
    """The operation collides with the resource's current state."""

    default_message: str = gettext_noop("Conflict.")
