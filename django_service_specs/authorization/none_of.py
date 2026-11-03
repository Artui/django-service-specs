"""``NoneOf`` - checks of which none may pass, as one check."""

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
    """Passes when none of its checks passes ``has_permission``: ``NoneOf(IsSuspended(), message=...)``.

    It inverts the class-level question alone, asking each check in order
    and refusing at the first that passes; its row and scope questions allow,
    as a ``PermissionCheck``'s do by default. So a check judging rows or a
    scope has no place inside it - the opposite of "may act on this row" is
    no rule a call can be refused by - and one whose ``has_object_permission``
    or ``has_scope_permission`` is its own, at any depth, is refused when
    this is built (test_none_of_refuses_a_row_level_child).

    ``message`` is what ``NotPermitted`` says when it refuses; ``None`` keeps
    the generic wording.
    """

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
    """The first row or scope method a leaf under ``check`` overrides, as ``Class.method``, else ``None``.

    A combinator is walked rather than read: its own row and scope methods
    are always its own, and what they ask is its children. Read off the bound
    method, so a callable set on the instance counts as an override too. One
    case per method in test_none_of_refuses_a_row_level_child, since either
    alone is a rule NoneOf cannot invert, and a depth-two case, with
    test_none_of_accepts_a_combinator_of_class_level_checks holding that the
    walk does not read the combinator itself.
    """
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
