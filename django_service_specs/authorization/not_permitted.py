from __future__ import annotations

from typing import ClassVar

from django_service_specs.types.dispatch_error import DispatchError
from django_service_specs.types.utils import gettext_noop


class NotPermitted(DispatchError):
    """A permission check refused the principal, or a grant did not cover the call."""

    default_message: ClassVar[str] = gettext_noop(
        "You do not have permission to perform this action."
    )
