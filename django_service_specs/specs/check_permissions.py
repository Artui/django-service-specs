from __future__ import annotations

from collections.abc import Sequence

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.authorization.utils import refuse_unusable_check


def check_permissions(
    permissions: Sequence[PermissionCheck] | None, *, label: str
) -> tuple[PermissionCheck, ...] | None:
    """Normalize ``permissions`` to a tuple of check instances, refusing anything else."""
    if permissions is None:
        return None
    if isinstance(permissions, str | bytes) or not isinstance(permissions, Sequence):
        raise ImproperlyConfigured(f"{label}.permissions must be a sequence of PermissionCheck.")
    checks = tuple(permissions)
    if not checks:
        raise ImproperlyConfigured(
            f"{label}.permissions is empty, which would let anyone run it. Declare "
            "permissions=[Unrestricted()] to mean that."
        )
    for index, check in enumerate(checks):
        refuse_unusable_check(check, label=f"{label}.permissions", index=index)
    return checks
