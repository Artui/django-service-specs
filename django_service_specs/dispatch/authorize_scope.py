"""``authorize_scope`` - the object-level check dispatch runs on a set, or on nothing."""

from __future__ import annotations

from typing import Any

from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.utils import sync_answer
from django_service_specs.dispatch.grant import Grant
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource


def authorize_scope(
    spec: ServiceSpec | SelectorSpec | SpecSource, principal: Any, scope: Any, *, grant: Grant
) -> None:
    """Run ``spec``'s scope-level permission checks against ``scope``.

    The counterpart of
    [`authorize_target`][django_service_specs.dispatch.authorize_target.authorize_target]
    for a call that resolves no single row: ``scope`` is the resolved set of a
    bulk or collection call, or ``None`` for a create. Every check's
    ``has_scope_permission`` must pass, in order, and the first refusal raises
    [`NotPermitted`][django_service_specs.authorization.not_permitted.NotPermitted]
    with that check's own message. An answer still to be awaited raises
    ``ImproperlyConfigured`` rather than being read as a pass. A
    [`SpecSource`][django_service_specs.specs.spec_source.SpecSource] is
    checked as the spec it compiles to.

    ``grant.target_checked`` skips the checks here as it does there: a
    transport that already ran the target-level checks has claimed them.
    Dispatch honours it, as there, only for a service spec's target handed
    in as ``target=``, so never on the list a selector spec reads.
    """
    spec = kernel_spec(spec)
    if grant.target_checked:
        return
    for check in spec.permissions or ():
        answer = check.has_scope_permission(principal, spec, scope)
        if not sync_answer(answer, asked=f"{type(check).__qualname__}.has_scope_permission"):
            raise NotPermitted(check.message)
