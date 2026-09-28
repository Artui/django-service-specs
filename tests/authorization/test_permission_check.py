from __future__ import annotations

from typing import Any

import pytest

from django_service_specs.authorization.permission_check import PermissionCheck


class _StaffOnly(PermissionCheck):
    message = "Staff only."

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return bool(getattr(principal, "is_staff", False))


def test_object_level_allows_unless_overridden() -> None:
    assert _StaffOnly().has_object_permission(None, None, object()) is True


def test_class_level_is_abstract() -> None:
    with pytest.raises(TypeError, match="abstract"):
        PermissionCheck()
