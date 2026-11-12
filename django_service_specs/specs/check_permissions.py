from __future__ import annotations

from collections.abc import Sequence

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.authorization.utils import refuse_unusable_check


def check_permissions(
    permissions: Sequence[PermissionCheck] | None, *, label: str
) -> tuple[PermissionCheck, ...] | None:
    """Normalize ``permissions`` to a tuple, refusing anything that is not a check *instance*, and
    an empty one.

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

    Each check is held to ``refuse_unusable_check``: an instance of
    ``PermissionCheck``, never its class, with three sync methods. A
    combinator is one such check, whose methods are sync, so its children are
    not walked here: it held them to the same rule when it was built.
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
        refuse_unusable_check(check, label=f"{label}.permissions", index=index)
    return checks
