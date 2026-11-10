from __future__ import annotations

from collections.abc import Callable, Sequence, Set
from typing import Any

from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.authorization.permission_check_denied import PermissionCheckDenied
from django_service_specs.dispatch.refusals import REFUSALS
from django_service_specs.parameters.coded_message import CodedMessage
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.services.action_unavailable import ActionUnavailable
from django_service_specs.services.additional_input_required import AdditionalInputRequired
from django_service_specs.services.service_error import ServiceError
from django_service_specs.services.service_validation_error import ServiceValidationError
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.types.dispatch_error import DispatchError
from django_service_specs.types.refusal_finding import RefusalFinding
from django_service_specs.types.refusal_finding_kind import RefusalFindingKind
from django_service_specs.types.selector_kind import SelectorKind


class _Denies(PermissionCheck):
    """The check a built ``PermissionCheckDenied`` names, which denies every caller."""

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return False


def _check_denied() -> PermissionCheckDenied:
    """A check's denial as ``authorize`` raises it, naming the check and the spec declaring it."""
    check = _Denies()
    spec = SelectorSpec(kind=SelectorKind.LIST, selector=list, permissions=[check])
    return PermissionCheckDenied(check=check, spec=spec)


_BUILDERS: dict[type[BaseException], Callable[[], DispatchError | ServiceError]] = {
    InvalidArguments: lambda: InvalidArguments(
        {"title": [CodedMessage("This field is required.", "required")]}
    ),
    PermissionCheckDenied: _check_denied,
    ServiceValidationError: lambda: ServiceValidationError("This value is invalid."),
    ActionUnavailable: lambda: ActionUnavailable(code="unavailable"),
    AdditionalInputRequired: lambda: AdditionalInputRequired("One more value is needed."),
}
"""The refusals whose constructor needs an argument; every other one is built bare.

Each built as a dispatch or a service raises it, so a map reading what it
carries - a tree, a code, a detail - reads a real one. The tree is the one the
shape check raises for a required argument nobody sent, its message a
``CodedMessage`` carrying ``"required"``. A check's denial names a check
denying every caller and a spec declaring it, so a map comparing its spec
with its own call's reads a denial of another call's."""


def unanswered_refusals(
    answers: Callable[[DispatchError | ServiceError], object]
    | Sequence[tuple[type[BaseException], object]],
    *,
    unanswered: object = None,
) -> tuple[RefusalFinding, ...]:
    """What a transport's map from the kernel's refusals to its outcomes leaves unanswered."""
    if callable(answers):
        answered = {kind for kind in REFUSALS if answers(_BUILDERS.get(kind, kind)()) != unanswered}
        shadowed: list[RefusalFinding] = []
    else:
        rows = tuple(answers)
        answered = {
            kind
            for kind in REFUSALS
            if next((outcome for row, outcome in rows if issubclass(kind, row)), unanswered)
            != unanswered
        }
        shadowed = _shadowed_rows([row for row, _ in rows])
    return (*(_unanswered(kind, answered) for kind in REFUSALS if kind not in answered), *shadowed)


def _unanswered(kind: type[BaseException], answered: Set[type[BaseException]]) -> RefusalFinding:
    """The finding for ``kind``, which nothing answers."""
    under = [other for other in REFUSALS if other is not kind and issubclass(other, kind)]
    if under and all(other in answered for other in under):
        return RefusalFinding(kind, RefusalFindingKind.BARE_BASE)
    return RefusalFinding(kind, RefusalFindingKind.UNANSWERED)


def _shadowed_rows(rows: list[type[BaseException]]) -> list[RefusalFinding]:
    """A finding for each row an earlier row of its own base, or its own class, already answers."""
    found = []
    for index, row in enumerate(rows):
        above = next((earlier for earlier in rows[:index] if issubclass(row, earlier)), None)
        if above is not None:
            found.append(RefusalFinding(row, RefusalFindingKind.SHADOWED_ROW, above))
    return found
