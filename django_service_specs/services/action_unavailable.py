from __future__ import annotations

from django_service_specs.services.service_conflict import ServiceConflict
from django_service_specs.types.utils import gettext_noop


class ActionUnavailable(ServiceConflict):
    """The operation is not possible right now, for a reason with a stable name."""

    default_message: str = gettext_noop("This action is not available right now.")

    def __init__(self, message: str | None = None, *, code: str) -> None:
        super().__init__(message)
        self.code: str = code
