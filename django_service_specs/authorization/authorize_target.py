"""``authorize_target`` - the object-level check dispatch runs on a resolved row."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django_service_specs.authorization.grant import Grant
from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.utils import compiled_spec, sync_answer

if TYPE_CHECKING:
    from django_service_specs.specs.selector_spec import SelectorSpec
    from django_service_specs.specs.service_spec import ServiceSpec
    from django_service_specs.specs.spec_source import SpecSource


def authorize_target(
    spec: ServiceSpec | SelectorSpec | SpecSource, principal: Any, target: Any, *, grant: Grant
) -> None:
    """Run ``spec``'s object-level permission checks against a resolved ``target``.

    Dispatch calls this on a retrieved row, never on a list: a collection has
    no single object to check against, and a member-level rule belongs to the
    presenter or the query that shaped it.

    ``grant.target_checked`` lets a transport that resolved the row itself and
    already ran the object-level check claim it once, so dispatch does not pay
    for it twice; dispatch honours it only for a service spec's target
    handed in as ``target=``, and never on a selector spec's row (see
    ``Grant``); otherwise every check's ``has_object_permission`` must pass,
    in order, and the first refusal raises
    [`NotPermitted`][django_service_specs.authorization.not_permitted.NotPermitted]
    with that check's own message. An answer still to be awaited raises
    ``ImproperlyConfigured`` rather than being read as a pass. A
    [`SpecSource`][django_service_specs.specs.spec_source.SpecSource] is
    checked as the spec it compiles to.

    ``spec.permissions is None`` means nothing to check here rather than a
    configuration error: [`authorize`][django_service_specs.authorization.authorize.authorize]
    already refused an undeclared spec before any target could be resolved, so
    this function is never reached with one - iterating an empty tuple in its
    place is simpler than asserting an invariant this module cannot enforce.
    """
    spec = compiled_spec(spec)
    if grant.target_checked:
        return
    for check in spec.permissions or ():
        answer = check.has_object_permission(principal, spec, target)
        if not sync_answer(answer, asked=f"{type(check).__qualname__}.has_object_permission"):
            raise NotPermitted(check.message)
