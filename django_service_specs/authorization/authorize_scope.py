"""``authorize_scope`` - the object-level check dispatch runs on a set, or on nothing."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django_service_specs.authorization.grant import Grant
from django_service_specs.authorization.not_permitted import NotPermitted

if TYPE_CHECKING:
    from django_service_specs.specs.selector_spec import SelectorSpec
    from django_service_specs.specs.service_spec import ServiceSpec


def authorize_scope(
    spec: ServiceSpec | SelectorSpec, principal: Any, scope: Any, *, grant: Grant
) -> None:
    """Run ``spec``'s scope-level permission checks against ``scope``.

    The counterpart of
    [`authorize_target`][django_service_specs.authorization.authorize_target.authorize_target]
    for a call that resolves no single row: ``scope`` is the resolved set of a
    bulk or collection call, or ``None`` for a create. Every check's
    ``has_scope_permission`` must pass, in order, and the first refusal raises
    [`NotPermitted`][django_service_specs.authorization.not_permitted.NotPermitted]
    with that check's own message.

    ``grant.target_checked`` skips the checks here as it does there: a
    transport that already ran the object-level check has claimed it.
    """
    if grant.target_checked:
        return
    for check in spec.permissions or ():
        if not check.has_scope_permission(principal, spec, scope):
            raise NotPermitted(check.message)
