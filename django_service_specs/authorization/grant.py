"""``Grant`` - a transport's statement that it has already authorized one call."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NoReturn

if TYPE_CHECKING:
    # Annotation-only, for the reason permission_check.py gives.
    from django_service_specs.specs.selector_spec import SelectorSpec
    from django_service_specs.specs.service_spec import ServiceSpec


@dataclass(frozen=True)
class Grant:
    """Proof that the class-level check already ran, for one spec and one principal.

    Dispatch enforces permissions by default. A transport that authorized
    through its own machinery first - an HTTP view running its framework's
    permission classes - passes a grant instead, rather than skipping the check
    by omission, and pays one class-level evaluation per call instead of two.

    **Bound to one spec and one principal**, by identity: a grant carried to
    another operation or another user covers nothing, and dispatch refuses it.

    ``target_checked`` says whether the object-level check ran too, which a
    transport can only claim once it has resolved the row itself. Without it,
    dispatch still runs ``has_object_permission`` on the row it resolves.

    **Not serializable.** Pickling one raises ``TypeError``, so a grant cannot
    ride a queue into a worker: a task runs minutes later against state that
    may have moved, and it re-authorizes by construction.
    """

    spec: ServiceSpec | SelectorSpec
    principal: Any
    target_checked: bool = False

    def covers(self, spec: ServiceSpec | SelectorSpec, principal: Any) -> bool:
        """Whether this grant is for exactly this spec and this principal."""
        return self.spec is spec and self.principal is principal

    def __reduce__(self) -> NoReturn:
        raise TypeError(
            "A Grant covers one call in one process and cannot be serialized. "
            "A worker re-authorizes with the principal it resolves."
        )
