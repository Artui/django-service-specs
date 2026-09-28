"""Permission-check test doubles shared by the authorization function tests."""

from __future__ import annotations

from typing import Any

from django_service_specs.authorization.permission_check import PermissionCheck


class Allow(PermissionCheck):
    """Passes at both levels, and records whether it was asked."""

    def __init__(self) -> None:
        self.class_level_calls = 0
        self.object_level_calls = 0

    def has_permission(self, principal: Any, spec: Any) -> bool:
        self.class_level_calls += 1
        return True

    def has_object_permission(self, principal: Any, spec: Any, target: Any) -> bool:
        self.object_level_calls += 1
        return True


class Refuse(PermissionCheck):
    """Refuses at both levels, with the default message."""

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return False

    def has_object_permission(self, principal: Any, spec: Any, target: Any) -> bool:
        return False


class RefuseWithMessage(PermissionCheck):
    """Refuses at both levels, naming its own message."""

    message = "Staff only."

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return False

    def has_object_permission(self, principal: Any, spec: Any, target: Any) -> bool:
        return False
