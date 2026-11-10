from __future__ import annotations

from typing import ClassVar

from django_service_specs.types.dispatch_error import DispatchError
from django_service_specs.types.utils import gettext_noop


class PrincipalUnavailable(DispatchError):
    """The principal cannot act: an identifier naming nobody, or a deactivated account."""

    default_message: ClassVar[str] = gettext_noop("The acting principal is unavailable.")
