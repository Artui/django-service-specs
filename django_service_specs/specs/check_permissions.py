"""``check_permissions``: the one rule a ``permissions=`` declaration is held to."""

from __future__ import annotations

from collections.abc import Sequence

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.specs.utils import check_callable

# The methods dispatch reads a permission check's answer from.
_CHECK_METHODS = ("has_permission", "has_object_permission", "has_scope_permission")


def check_permissions(
    permissions: Sequence[PermissionCheck] | None, *, label: str
) -> tuple[PermissionCheck, ...] | None:
    """Normalize ``permissions`` to a tuple, refusing anything that is not a check *instance*, and an empty one.

    Called by ``ServiceSpec`` and ``SelectorSpec`` on their ``permissions=``,
    and by a transport that accepts ``PermissionCheck``s on something other
    than a spec - a prompt, a view - so that it normalizes and refuses them by
    the rules a spec's ``permissions=`` gets, rather than by a copy of its
    own. ``None`` comes back as ``None``, for the caller to refuse or allow as
    its own default says. A refusal is ``ImproperlyConfigured``, and ``label``
    names the declaration it is raised for, as ``Class.permissions``.

    **An empty sequence is refused**, as ``None`` is refused at dispatch and
    at registration: every check passing is vacuously true of no checks, so
    ``permissions=[]`` would let anyone run the operation, and an empty list
    is as often computed by accident as decided. ``Unrestricted()`` is the
    decision, by name (test_an_empty_permissions_sequence_is_refused).

    A class is the likely mistake - an HTTP framework declares permission
    classes - and a class passes ``callable()``, so it is refused by name here
    rather than failing at dispatch with an unbound-method error.

    Each of the three methods is read for truth from sync code, so an
    ``async def`` one - whose answer is a truthy coroutine - is refused here,
    on the bound method, as any other sync-only seat is. One case per method
    in ``tests/specs/test_check_permissions.py``'s ``TestAnAsyncPermissionCheckIsRefused``,
    since coverage cannot see a name dropped from ``_CHECK_METHODS``. What
    construction cannot see, a plain ``def`` handing back a coroutine, is
    refused where the answer is read, by ``sync_answer``.
    """
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
        if isinstance(check, type):
            raise ImproperlyConfigured(
                f"{label}.permissions holds the class {check.__name__}; pass an instance, "
                f"{check.__name__}()."
            )
        if not isinstance(check, PermissionCheck):
            raise ImproperlyConfigured(
                f"{label}.permissions holds {type(check).__name__}, which is not a "
                "PermissionCheck. Subclass PermissionCheck, or adapt it."
            )
        for method in _CHECK_METHODS:
            check_callable(
                getattr(check, method), label=f"{label}.permissions[{index}].{method}", sync=True
            )
    return checks
