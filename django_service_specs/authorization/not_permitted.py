"""``NotPermitted`` - the acting principal may not do this."""

from __future__ import annotations

from typing import ClassVar

from django_service_specs.types.dispatch_error import DispatchError


class NotPermitted(DispatchError):
    """A permission check refused the principal, or a grant did not cover the call.

    Named for what a failed ``has_permission`` means, literally. Not
    ``PermissionDenied``, which Django and DRF both own for their own
    exceptions, and not a service error: a model that reads a denial as a
    refusal to route around keeps trying, where a denial should end the attempt.
    """

    default_message: ClassVar[str] = "You do not have permission to perform this action."
