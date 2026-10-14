"""``Unrestricted`` - the explicit allow."""

from __future__ import annotations

from typing import Any

from django_service_specs.authorization.permission_check import PermissionCheck


class Unrestricted(PermissionCheck):
    """Anyone may run this spec: ``permissions=[Unrestricted()]``.

    A spec that declares no permissions is refused at registration and at
    dispatch, because off HTTP there is no view whose policy it could inherit,
    and running it anyway is how an off-HTTP runner skips authorization with
    nothing warning. An operation that is genuinely open says so with this.

    A named class rather than an empty list, so every open operation in a
    project is one search away, and an empty list computed by accident is not
    read as a decision: a spec handed one is refused when it is built.
    """

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return True
