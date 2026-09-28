from __future__ import annotations

from django_service_specs.authorization.unrestricted import Unrestricted


def test_allows_anyone_at_both_levels() -> None:
    check = Unrestricted()
    assert check.has_permission(None, None) is True
    assert check.has_object_permission(None, None, object()) is True
    assert check.message is None
