"""``PermissionCheck`` - the kernel's permission contract."""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Annotation-only: the spec modules import this one to declare their
    # ``permissions`` field, so a runtime import here would be circular.
    from django_service_specs.specs.selector_spec import SelectorSpec
    from django_service_specs.specs.service_spec import ServiceSpec


class PermissionCheck(abc.ABC):
    """Whether a principal may run a spec, and whether they may act on a row.

    A principal and a spec, and nothing else: no request and no view, because
    most transports have neither. Instances rather than classes, so a check can
    carry its own configuration (a codename, a group) and a spec reads as the
    list of checks it applies.

    ``has_permission`` is the class-level check, run before any row is resolved,
    so a principal refused here learns nothing about which rows exist.
    ``has_object_permission`` runs against the resolved target of a retrieve or
    an update; it allows by default, because most checks are class-level only.

    ``message`` is what [`NotPermitted`][django_service_specs.authorization.not_permitted.NotPermitted]
    says when this check refuses; ``None`` keeps the generic wording.

    **Sync-only**, like every concept: a check may query, so the async path runs
    it in the executor.
    """

    message: str | None = None

    @abc.abstractmethod
    def has_permission(self, principal: Any, spec: ServiceSpec | SelectorSpec) -> bool:
        """Whether ``principal`` may run ``spec`` at all."""

    def has_object_permission(
        self, principal: Any, spec: ServiceSpec | SelectorSpec, target: Any
    ) -> bool:
        """Whether ``principal`` may act on ``target``. Allows unless overridden."""
        return True
