"""``PermissionCheckDenied`` - a declared permission check answered no."""

from __future__ import annotations

from typing import Any

from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.permission_check import PermissionCheck


class PermissionCheckDenied(NotPermitted):
    """A permission check the spec declares answered ``False``.

    Raised by [`authorize`][django_service_specs.dispatch.authorize.authorize],
    [`authorize_target`][django_service_specs.dispatch.authorize_target.authorize_target]
    and [`authorize_scope`][django_service_specs.dispatch.authorize_scope.authorize_scope]
    when one of the spec's checks answers ``False``, and by nothing else. Every
    other ``NotPermitted`` stays bare: a grant or a seeds carrier that does not
    cover the call, a service's own refusal, and a check that raises
    ``NotPermitted`` itself, which propagates as raised. So a transport can
    answer a check's denial of an anonymous caller as an authentication
    challenge, as DRF's ``permission_denied`` does, without turning any other
    refusal into a sign-in prompt.

    ``check`` is the check that answered: the combinator, for a check inside
    [`AllOf`][django_service_specs.authorization.all_of.AllOf],
    [`AnyOf`][django_service_specs.authorization.any_of.AnyOf] or
    [`NoneOf`][django_service_specs.authorization.none_of.NoneOf], since that is
    the rule the spec declares. The message is the check's ``message``, or the
    default wording when it has none.

    ``spec`` is the spec the check was asked about, as a spec of this
    package's: a declaration of another library's is named by what
    [`kernel_spec`][django_service_specs.specs.kernel_spec.kernel_spec] compiles
    it to. It is there because a denial inside a service's own ``dispatch``
    propagates out of the outer call as the same class, so the class alone
    cannot say whose check refused: a transport treats a denial as its own
    call's only where ``exc.spec is kernel_spec(spec)`` for the spec it
    dispatched. ``Any``, as ``PermissionCheck`` names it, because the spec
    modules import this package.
    """

    def __init__(self, *, check: PermissionCheck, spec: Any) -> None:
        super().__init__(check.message)
        self.check: PermissionCheck = check
        self.spec: Any = spec
