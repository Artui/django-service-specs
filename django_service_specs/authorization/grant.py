"""``Grant`` - a transport's statement that it has already authorized one call."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NoReturn

from django_service_specs.authorization.utils import compiled_spec

if TYPE_CHECKING:
    # Annotation-only, for the reason permission_check.py gives.
    from django_service_specs.specs.selector_spec import SelectorSpec
    from django_service_specs.specs.service_spec import ServiceSpec
    from django_service_specs.specs.spec_source import SpecSource


@dataclass(frozen=True)
class Grant:
    """Proof that the class-level check already ran, for one spec and one principal.

    Dispatch enforces permissions by default. A transport that authorized
    through its own machinery first - an HTTP view running its framework's
    permission classes - passes a grant instead, rather than skipping the check
    by omission, and pays one class-level evaluation per call instead of two.

    **Bound to one spec and one principal**, by identity: a grant carried to
    another operation or another user covers nothing, and dispatch refuses it.

    ``target_checked`` says the target-level checks ran too -
    ``has_object_permission`` on a row, ``has_scope_permission`` on a set or
    on nothing - which a transport can only claim once it has resolved the
    target itself. It covers **the target handed to dispatch as**
    ``target=``, **and nothing else**: dispatch skips the checks only on that
    target. When dispatch looks the target up itself, from the arguments, it
    runs them whatever the grant says, since the row it finds may not be the
    one the grant was minted for. ``resolve_target`` mints such a grant for
    the target it returns, to be handed on with it. A selector spec takes no
    ``target=``, so on one the flag covers nothing: its selector finds the
    row or the list from the arguments, and the checks run on what it
    found.

    Without it, dispatch runs those checks on what it resolves.

    **Not serializable.** Pickling one raises ``TypeError``, so a grant cannot
    ride a queue into a worker: a task runs minutes later against state that
    may have moved, and it re-authorizes by construction.
    """

    spec: ServiceSpec | SelectorSpec | SpecSource
    principal: Any
    target_checked: bool = False

    def covers(self, spec: ServiceSpec | SelectorSpec | SpecSource, principal: Any) -> bool:
        """Whether this grant is for exactly this spec and this principal.

        The spec is compared as compiled: a grant minted for a
        [`SpecSource`][django_service_specs.specs.spec_source.SpecSource]
        covers that object and the spec it compiles to, and a grant minted for
        the compiled spec covers the object, since each compiles once. Another
        object, even one comparing equal, compiles to another spec and is not
        covered.
        """
        # Compiled here rather than when the grant is built, so ``spec`` keeps
        # the object the transport gave it. One arc to coverage, so each
        # operand is named: test_a_grant_for_a_source_covers_the_source_and_the_spec_it_compiles_to
        # holds both, by another declaration and another principal.
        return self.principal is principal and compiled_spec(self.spec) is compiled_spec(spec)

    def __reduce__(self) -> NoReturn:
        raise TypeError(
            "A Grant covers one call in one process and cannot be serialized. "
            "A worker re-authorizes with the principal it resolves."
        )
