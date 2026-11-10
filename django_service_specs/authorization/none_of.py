from __future__ import annotations

from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.authorization.utils import (
    CLASS_LEVEL,
    OBJECT_LEVEL,
    SCOPE_LEVEL,
    _Combinator,
)


class NoneOf(_Combinator):
    """Passes when none of its checks passes ``has_permission``: ``NoneOf(IsSuspended(),
    message=...)``."""

    _asks = {
        CLASS_LEVEL[0]: (CLASS_LEVEL,),
        OBJECT_LEVEL[0]: (),
        SCOPE_LEVEL[0]: (),
    }

    def __init__(self, *checks: PermissionCheck, message: str | None = None) -> None:
        super().__init__(*checks, message=message)
        for index, check in enumerate(self.checks):
            judged = _judges_rows(check)
            if judged is not None:
                raise ImproperlyConfigured(
                    f"NoneOf.checks[{index}] judges rows: {judged} is its own, and NoneOf "
                    "inverts has_permission alone, so that rule would never be asked. Combine "
                    "it outside NoneOf."
                )

    def has_permission(self, principal: Any, spec: Any, **offered: Any) -> bool:
        return not any(
            self._passes(check, CLASS_LEVEL[0], principal, spec, (), offered)
            for check in self.checks
        )


def _judges_rows(check: PermissionCheck) -> str | None:
    """The ``Class.method`` a leaf under ``check`` overrides first, or ``None``."""
    if isinstance(check, _Combinator):
        return next(
            (judged for child in check.checks if (judged := _judges_rows(child)) is not None),
            None,
        )
    for method in (OBJECT_LEVEL[0], SCOPE_LEVEL[0]):
        if getattr(getattr(check, method), "__func__", None) is not getattr(
            PermissionCheck, method
        ):
            return f"{type(check).__qualname__}.{method}"
    return None
