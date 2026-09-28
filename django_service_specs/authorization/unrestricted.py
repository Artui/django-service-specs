"""``Unrestricted`` - the explicit allow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django_service_specs.authorization.permission_check import PermissionCheck

if TYPE_CHECKING:
    # Annotation-only, for the reason permission_check.py gives.
    from django_service_specs.specs.selector_spec import SelectorSpec
    from django_service_specs.specs.service_spec import ServiceSpec


class Unrestricted(PermissionCheck):
    """Anyone may run this spec: ``permissions=[Unrestricted()]``.

    A spec that declares no permissions is refused at registration and at
    dispatch, because off HTTP there is no view whose policy it could inherit,
    and running it anyway is how an off-HTTP runner skips authorization with
    nothing warning. An operation that is genuinely open says so with this.

    A named class rather than an empty list, so every open operation in a
    project is one search away, and an empty list computed by accident is not
    read as a decision.
    """

    def has_permission(self, principal: Any, spec: ServiceSpec | SelectorSpec) -> bool:
        return True
