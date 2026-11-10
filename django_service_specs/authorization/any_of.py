from __future__ import annotations

from typing import Any

from django_service_specs.authorization.utils import (
    CLASS_LEVEL,
    OBJECT_LEVEL,
    SCOPE_LEVEL,
    _Combinator,
)


class AnyOf(_Combinator):
    """Passes when one of its checks passes: ``AnyOf(IsOwner(), IsStaff(), message=...)``."""

    _asks = {
        CLASS_LEVEL[0]: (CLASS_LEVEL,),
        OBJECT_LEVEL[0]: (CLASS_LEVEL, OBJECT_LEVEL),
        SCOPE_LEVEL[0]: (CLASS_LEVEL, SCOPE_LEVEL),
    }

    def has_permission(self, principal: Any, spec: Any, **offered: Any) -> bool:
        return any(
            self._passes(check, CLASS_LEVEL[0], principal, spec, (), offered)
            for check in self.checks
        )

    def has_object_permission(self, principal: Any, spec: Any, target: Any, **offered: Any) -> bool:
        return any(
            self._passes(check, OBJECT_LEVEL[0], principal, spec, (target,), offered)
            for check in self.checks
        )

    def has_scope_permission(self, principal: Any, spec: Any, scope: Any, **offered: Any) -> bool:
        return any(
            self._passes(check, SCOPE_LEVEL[0], principal, spec, (scope,), offered)
            for check in self.checks
        )
