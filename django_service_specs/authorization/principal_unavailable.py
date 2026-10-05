"""``PrincipalUnavailable`` - the acting principal cannot act at all."""

from __future__ import annotations

from typing import ClassVar

from django_service_specs.types.dispatch_error import DispatchError


class PrincipalUnavailable(DispatchError):
    """The principal cannot act: an identifier naming nobody, or a deactivated account.

    Raised by ``resolve_principal`` for an identifier that is missing,
    malformed or names a deactivated row, and by dispatch and the HTTP entry
    points for a deactivated principal they were handed. Either way it comes
    before any permission check, which is about what a principal may do, not
    whether there is one.

    Terminal. Never a fallback to ``AnonymousUser``, which would run the
    operation as somebody the caller did not name, and never a retry: a deleted
    row does not come back, and a deactivated account is deactivated on purpose.
    """

    default_message: ClassVar[str] = "The acting principal is unavailable."
