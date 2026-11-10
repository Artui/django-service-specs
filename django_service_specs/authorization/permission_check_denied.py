from __future__ import annotations

from typing import Any

from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.permission_check import PermissionCheck


class PermissionCheckDenied(NotPermitted):
    """A permission check the spec declares answered ``False``."""

    def __init__(self, *, check: PermissionCheck, spec: Any) -> None:
        super().__init__(check.message)
        self.check: PermissionCheck = check
        self.spec: Any = spec
