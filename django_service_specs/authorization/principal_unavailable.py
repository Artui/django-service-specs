"""``PrincipalUnavailable`` - the principal named off HTTP cannot act."""

from __future__ import annotations

from typing import ClassVar

from django_service_specs.types.dispatch_error import DispatchError


class PrincipalUnavailable(DispatchError):
    """The identifier names no user who may act: missing, malformed, or deactivated.

    Terminal. Never a fallback to ``AnonymousUser``, which would run the
    operation as somebody the caller did not name, and never a retry: a deleted
    row does not come back, and a deactivated account is deactivated on purpose.
    """

    default_message: ClassVar[str] = "The acting principal is unavailable."
