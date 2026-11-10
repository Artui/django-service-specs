from __future__ import annotations

from typing import Any

from django_service_specs.authorization.permission_check import PermissionCheck


class Unrestricted(PermissionCheck):
    """Anyone may run this spec: ``permissions=[Unrestricted()]``."""

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return True
