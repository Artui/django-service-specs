"""``AnyOf`` - checks of which one passing is enough, as one check."""

from __future__ import annotations

from typing import Any

from django_service_specs.authorization.utils import (
    CLASS_LEVEL,
    OBJECT_LEVEL,
    SCOPE_LEVEL,
    _Combinator,
)


class AnyOf(_Combinator):
    """Passes when one of its checks passes: ``AnyOf(IsOwner(), IsStaff(), message=...)``.

    ``has_permission`` asks each check in order and stops at the first that
    passes (test_any_of_does_not_ask_past_the_first_pass).

    At the row and scope questions a check counts only where it passes the
    class-level question too, asked again, and then that question: an owner
    rule that allows any row by default must not let through a principal it
    refused at class level because another check admitted them there. Two
    questions asked of each check in turn, the first failing skipping the
    second, and each has a test that fails without it: dropping the
    class-level one fails test_any_of_row_question_skips_a_child_refused_at_class_level
    and test_any_of_scope_question_skips_a_child_refused_at_class_level, and
    dropping the row or scope one fails the same two tests, whose other check
    passes at class level and refuses the row or the scope. The class-level
    question is asked again rather than remembered from the class-level call,
    so the answer holds under a grant that covered that call and asked
    nothing (test_any_of_under_a_covering_grant_still_judges_the_row), and
    nothing is written to the call's context. A check that opts into a seed
    or the arguments at the class-level question is handed them at the row
    and scope questions too, since it is asked there.

    ``message`` is what ``NotPermitted`` says when it refuses; ``None`` keeps
    the generic wording.
    """

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
