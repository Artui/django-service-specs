from __future__ import annotations

from typing import Any

from django_service_specs.authorization.utils import (
    CLASS_LEVEL,
    OBJECT_LEVEL,
    QUESTIONS,
    SCOPE_LEVEL,
    _Combinator,
)


class AllOf(_Combinator):
    """Passes when every check passes: ``AllOf(IsStaff(), InTenant(), message=...)``.

    What a spec's ``permissions=`` list already means, as one check, so it can
    stand inside ``AnyOf`` or ``NoneOf``. Each of the three questions asks
    every check the same question, in order, and stops at the first that
    fails (test_all_of_does_not_ask_past_the_first_refusal). ``message`` is
    what ``NotPermitted`` says when it refuses; ``None`` keeps the generic
    wording.
    """

    _asks = {method: ((method, filled),) for method, filled in QUESTIONS}

    def has_permission(self, principal: Any, spec: Any, **offered: Any) -> bool:
        return all(
            self._passes(check, CLASS_LEVEL[0], principal, spec, (), offered)
            for check in self.checks
        )

    def has_object_permission(self, principal: Any, spec: Any, target: Any, **offered: Any) -> bool:
        return all(
            self._passes(check, OBJECT_LEVEL[0], principal, spec, (target,), offered)
            for check in self.checks
        )

    def has_scope_permission(self, principal: Any, spec: Any, scope: Any, **offered: Any) -> bool:
        return all(
            self._passes(check, SCOPE_LEVEL[0], principal, spec, (scope,), offered)
            for check in self.checks
        )
