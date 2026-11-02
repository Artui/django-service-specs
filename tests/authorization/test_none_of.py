from __future__ import annotations

import re
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.all_of import AllOf
from django_service_specs.authorization.any_of import AnyOf
from django_service_specs.authorization.none_of import NoneOf
from django_service_specs.authorization.permission_check import PermissionCheck
from tests.authorization.utils import Answers, ClassLevel, refuses

_PRINCIPAL, _SPEC, _ROW = object(), object(), object()


def test_none_of_allows_when_no_check_passes() -> None:
    log: list[str] = []
    check = NoneOf(ClassLevel("a", log, permission=False), ClassLevel("b", log, permission=False))
    assert check.has_permission(_PRINCIPAL, _SPEC) is True
    assert log == ["a.has_permission", "b.has_permission"]


def test_none_of_refuses_at_the_first_check_that_passes() -> None:
    log: list[str] = []
    check = NoneOf(ClassLevel("a", log), ClassLevel("b", log))
    assert check.has_permission(_PRINCIPAL, _SPEC) is False
    assert log == ["a.has_permission"]


@pytest.mark.parametrize("method", ["has_object_permission", "has_scope_permission"])
def test_the_row_and_scope_questions_allow_without_asking(method: str) -> None:
    log: list[str] = []
    check = NoneOf(ClassLevel("a", log))
    assert getattr(check, method)(_PRINCIPAL, _SPEC, _ROW) is True
    assert log == []


class _ClassAnswer(PermissionCheck):
    """Answers the class-level question with what it was built with, from a plain ``def``."""

    def __init__(self, answer: Any) -> None:
        self.answer = answer

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return self.answer


def test_none_of_none_of_a_coroutine_answer_is_refused() -> None:
    # Read as it stands, the truthy coroutine makes the inner NoneOf refuse,
    # which the outer one turns into an allow.
    check = NoneOf(NoneOf(_ClassAnswer(refuses())))
    with pytest.raises(ImproperlyConfigured, match=r"_ClassAnswer\.has_permission answered"):
        check.has_permission(_PRINCIPAL, _SPEC)


class _RowLevel(PermissionCheck):
    def has_permission(self, principal: Any, spec: Any) -> bool:
        return True

    def has_object_permission(self, principal: Any, spec: Any, target: Any) -> bool:
        return False


class _ScopeLevel(PermissionCheck):
    def has_permission(self, principal: Any, spec: Any) -> bool:
        return True

    def has_scope_permission(self, principal: Any, spec: Any, scope: Any) -> bool:
        return False


def _shadowed() -> PermissionCheck:
    """A class-level check whose row question is a callable set on the instance."""
    check = ClassLevel("a", [])
    check.has_object_permission = lambda principal, spec, target: False  # ty: ignore[invalid-assignment]
    return check


class TestNoneOfRefusesARowLevelChild:
    """Inverting a row or scope rule is no rule, so a check holding one is refused, at any depth."""

    @pytest.mark.parametrize(
        ("child", "named"),
        [
            (_RowLevel(), "_RowLevel.has_object_permission"),
            (_ScopeLevel(), "_ScopeLevel.has_scope_permission"),
            (_shadowed(), "ClassLevel.has_object_permission"),
        ],
        ids=["row", "scope", "shadowed-on-the-instance"],
    )
    def test_none_of_refuses_a_row_level_child(self, child: PermissionCheck, named: str) -> None:
        with pytest.raises(
            ImproperlyConfigured, match=re.escape(f"NoneOf.checks[1] judges rows: {named}")
        ):
            NoneOf(ClassLevel("a", []), child)

    def test_at_depth_two(self) -> None:
        with pytest.raises(
            ImproperlyConfigured,
            match=re.escape("NoneOf.checks[0] judges rows: _ScopeLevel.has_scope_permission"),
        ):
            NoneOf(AllOf(ClassLevel("a", []), AnyOf(ClassLevel("b", []), _ScopeLevel())))

    def test_none_of_accepts_a_combinator_of_class_level_checks(self) -> None:
        # A combinator's own row and scope methods are always its own; the
        # walk reads its children instead.
        log: list[str] = []
        check = NoneOf(AllOf(ClassLevel("a", log), ClassLevel("b", log, permission=False)))
        assert check.has_permission(_PRINCIPAL, _SPEC) is True
        assert log == ["a.has_permission", "b.has_permission"]

    def test_a_check_overriding_both_is_refused(self) -> None:
        with pytest.raises(ImproperlyConfigured, match=r"NoneOf\.checks\[1\] judges rows"):
            NoneOf(ClassLevel("a", []), Answers("b", []))


def test_an_empty_combinator_is_refused() -> None:
    # No check passing is vacuously true of none, so an empty NoneOf would let
    # anyone run the operation it guards.
    with pytest.raises(ImproperlyConfigured, match=r"NoneOf\.checks is empty"):
        NoneOf()
