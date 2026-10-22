"""``authorize`` - the class-level check dispatch runs before resolving a target."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.utils import asked_with, offered_to_checks, sync_answer
from django_service_specs.dispatch.grant import Grant
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource


def authorize(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    principal: Any,
    *,
    grant: Grant | None = None,
    arguments: Mapping[str, Any] | None = None,
    call_context: dict[str, Any] | None = None,
    seeds: Mapping[str, Any] | None = None,
) -> Grant:
    """Run ``spec``'s class-level permission checks for ``principal``.

    Dispatch enforces this by default. A transport that already authorized
    through its own machinery - an HTTP view running its framework's
    permission classes - passes the ``Grant`` it produced instead of paying for
    a second evaluation; the grant is honoured only if it
    [`covers`][django_service_specs.dispatch.grant.Grant.covers] this exact
    spec and principal, by identity, so a grant carried over from another
    operation or another user is refused rather than trusted.

    ``spec`` may be a
    [`SpecSource`][django_service_specs.specs.spec_source.SpecSource]: each
    check is asked about the spec it compiles to, the object dispatch hands
    it for the same declaration, and the grant returned covers both.

    Without a grant, ``spec.permissions is None`` is a configuration error, not
    the principal's fault: off HTTP there is no view whose policy an
    undeclared spec could inherit, so an operation that means to be open says
    so with ``permissions=[Unrestricted()]``.

    Otherwise every check's ``has_permission`` must pass, in order; the first
    refusal raises
    [`NotPermitted`][django_service_specs.authorization.not_permitted.NotPermitted]
    with that check's own message, or the generic one when it declares none.
    An answer still to be awaited - a coroutine from a check that is not
    sync - raises ``ImproperlyConfigured`` rather than being read as a pass.

    ``arguments`` is handed to each check's method that declares a keyword
    of that name, and to no other, so a check that declares none is asked
    without it. Dispatch passes the call's
    shape-checked arguments as a read-only mapping, whose values are the
    call's own and must not be mutated; ``None`` when the caller has none to
    hand.

    ``call_context`` and ``seeds`` are offered the same way, by name: a
    method declaring ``call_context`` is handed the call's context - the dict
    the transport handed dispatch, a fresh one when it handed none or this is
    called without one - and a method naming a registered seed is handed that
    seed's value from ``seeds``, which dispatch resolves for the call only
    when one of the spec's checks names one. A parameter the call fills by
    position is never read as an opt-in, whatever its name.

    Returns:
        The grant that was honoured, or a freshly minted one covering this
        spec and principal.
    """
    spec = kernel_spec(spec)
    if grant is not None:
        if grant.covers(spec, principal):
            return grant
        raise NotPermitted("The grant does not cover this spec and principal.")
    if spec.permissions is None:
        # Named by its run rather than by ``repr(spec)``: a frozen dataclass
        # repr prints every field, which buries the one name that says which
        # declaration to fix.
        run = getattr(spec, "service", None) or getattr(spec, "selector", None)
        raise ImproperlyConfigured(
            f"The {type(spec).__name__} for {getattr(run, '__qualname__', run)!s} declares "
            "no permissions. Pass permissions=[Unrestricted()] to mean that anyone may run it."
        )
    offered = offered_to_checks(call_context, seeds)
    for check in spec.permissions:
        answer = check.has_permission(
            principal, spec, **asked_with(check, "has_permission", arguments, offered=offered)
        )
        if not sync_answer(answer, asked=f"{type(check).__qualname__}.has_permission"):
            raise NotPermitted(check.message)
    return Grant(spec, principal)
