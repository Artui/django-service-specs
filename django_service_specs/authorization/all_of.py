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
    """Passes when every check passes: ``AllOf(IsStaff(), InTenant(), message=...)``."""

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
