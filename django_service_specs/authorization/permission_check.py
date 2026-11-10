from __future__ import annotations

import abc
from typing import Any


class PermissionCheck(abc.ABC):
    """Whether a principal may run a spec, and whether they may act on a row."""

    message: str | None = None

    @abc.abstractmethod
    def has_permission(self, principal: Any, spec: Any) -> bool:
        """Whether ``principal`` may run ``spec`` at all."""

    def has_object_permission(self, principal: Any, spec: Any, target: Any) -> bool:
        """Whether ``principal`` may act on ``target``."""
        return True

    def has_scope_permission(self, principal: Any, spec: Any, scope: Any) -> bool:
        """Whether ``principal`` may act on ``scope``."""
        return True
