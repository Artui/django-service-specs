from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.all_of import AllOf
from django_service_specs.authorization.any_of import AnyOf
from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.dispatch.authorize import authorize
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.types.selector_kind import SelectorKind
from tests.authorization.utils import Allow, Answers, AnswersWith, opting_into, refuses

_PRINCIPAL, _SPEC, _ROW = object(), object(), object()


def test_any_of_passes_when_one_check_passes() -> None:
    log: list[str] = []
    check = AnyOf(Answers("a", log, permission=False), Answers("b", log))
    assert check.has_permission(_PRINCIPAL, _SPEC) is True
    assert log == ["a.has_permission", "b.has_permission"]


def test_any_of_refuses_when_no_check_passes() -> None:
    log: list[str] = []
    check = AnyOf(Answers("a", log, permission=False), Answers("b", log, permission=False))
    assert check.has_permission(_PRINCIPAL, _SPEC) is False


def test_any_of_does_not_ask_past_the_first_pass() -> None:
    log: list[str] = []
    check = AnyOf(Answers("a", log), Answers("b", log))
    assert check.has_permission(_PRINCIPAL, _SPEC) is True
    assert log == ["a.has_permission"]


@pytest.mark.parametrize(
    ("method", "refusing"),
    [("has_object_permission", {"row": False}), ("has_scope_permission", {"scope": False})],
)
def test_the_row_and_scope_questions_stop_at_the_first_check_passing_both(
    method: str, refusing: dict[str, Any]
) -> None:
    log: list[str] = []
    check = AnyOf(Answers("a", log, **refusing), Answers("b", log), Answers("c", log))
    assert getattr(check, method)(_PRINCIPAL, _SPEC, _ROW) is True
    assert log == ["a.has_permission", f"a.{method}", "b.has_permission", f"b.{method}"]


def test_a_child_answering_a_coroutine_does_not_pass_any_of() -> None:
    # A plain ``def`` handing back a coroutine looks sync when the combinator
    # is built; the coroutine is truthy, so read as it stands it would pass.
    check = AnyOf(AnswersWith(refuses()))
    with pytest.raises(ImproperlyConfigured, match=r"AnswersWith\.has_permission answered"):
        check.has_permission(_PRINCIPAL, _SPEC)


class _Raises(PermissionCheck):
    def has_permission(self, principal: Any, spec: Any) -> bool:
        raise LookupError("the membership service is down")


def test_a_child_raising_is_not_read_as_a_refusal() -> None:
    # Read as a refusal, the next check would be asked and pass: an error in
    # one rule would let the call through on another.
    check = AnyOf(_Raises(), Allow())
    with pytest.raises(LookupError, match="the membership service is down"):
        check.has_permission(_PRINCIPAL, _SPEC)


class _Plain(PermissionCheck):
    """Declares no keyword, so one handed any would raise ``TypeError``."""

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return False


class _TakesArguments(PermissionCheck):
    def __init__(self) -> None:
        self.handed: list[Mapping[str, Any] | None] = []

    def has_permission(self, principal: Any, spec: Any, *, arguments: Any) -> bool:
        self.handed.append(arguments)
        return False


class _TakesTenant(PermissionCheck):
    def __init__(self) -> None:
        self.handed: list[tuple[Any, Any]] = []

    def has_permission(self, principal: Any, spec: Any, *, call_context: Any, tenant: Any) -> bool:
        self.handed.append((call_context, tenant))
        return False


def test_a_child_is_handed_only_what_it_declares() -> None:
    plain, arguing, tenanted = _Plain(), _TakesArguments(), _TakesTenant()
    spec = SelectorSpec(
        kind=SelectorKind.LIST, selector=list, permissions=[AnyOf(plain, arguing, tenanted)]
    )
    context: dict[str, Any] = {"seen": True}
    with pytest.raises(NotPermitted):
        authorize(
            spec,
            object(),
            arguments={"pk": 3},
            call_context=context,
            seeds={"tenant": "acme", "locale": "hr"},
        )
    assert [dict(a or {}) for a in arguing.handed] == [{"pk": 3}]
    assert tenanted.handed == [(context, "acme")]
    assert tenanted.handed[0][0] is context


def test_a_combinator_is_equal_only_to_itself() -> None:
    check = Allow()
    combined = AnyOf(check)
    assert combined == combined
    assert combined != AnyOf(check)


def test_an_empty_combinator_is_refused() -> None:
    with pytest.raises(ImproperlyConfigured, match=r"AnyOf\.checks is empty"):
        AnyOf()


class _OpenToAll(Unrestricted):
    """A project's own name for the explicit allow."""


@pytest.mark.parametrize("unrestricted", [Unrestricted(), _OpenToAll()], ids=["it", "a-subclass"])
class TestUnrestrictedInsideACombinatorIsRefused:
    """The explicit allow is a spec's decision, by name; inside a combinator it decides for it."""

    def test_unrestricted_inside_a_combinator_is_refused(self, unrestricted: Unrestricted) -> None:
        named = f"AnyOf.checks[1] is {type(unrestricted).__name__}, the explicit allow"
        with pytest.raises(ImproperlyConfigured, match=re.escape(named)):
            AnyOf(Allow(), unrestricted)

    def test_at_depth_two(self, unrestricted: Unrestricted) -> None:
        # Refused as the inner combinator is built, before the outer one could
        # be: AnyOf(staff, AllOf(Unrestricted())) would let anyone in.
        named = f"AllOf.checks[0] is {type(unrestricted).__name__}, the explicit allow"
        with pytest.raises(ImproperlyConfigured, match=re.escape(named)):
            AnyOf(Allow(), AllOf(unrestricted))


_HP, _HOP, _HSP = "has_permission", "has_object_permission", "has_scope_permission"


@pytest.mark.parametrize(
    ("declared_at", "name", "takes_it_at"),
    [
        (_HP, "principal", _HP),
        (_HP, "spec", _HP),
        # Asked again at the row and scope questions, so its class-level
        # opt-in meets the parameter those methods take.
        (_HP, "target", _HOP),
        (_HP, "scope", _HSP),
        (_HOP, "principal", _HOP),
        (_HOP, "spec", _HOP),
        (_HOP, "target", _HOP),
        (_HSP, "principal", _HSP),
        (_HSP, "spec", _HSP),
        (_HSP, "scope", _HSP),
    ],
)
def test_a_child_naming_a_parameter_of_any_of_is_refused(
    declared_at: str, name: str, takes_it_at: str
) -> None:
    named = (
        f"AnyOf.checks[1] opts into a seed named '{name}' at {declared_at}, and "
        f"AnyOf.{takes_it_at} takes {name} itself, so a seed of that name cannot reach "
        "the child through it. Rename the keyword."
    )
    with pytest.raises(ImproperlyConfigured, match=re.escape(named)):
        AnyOf(Allow(), opting_into(name, declared_at))


def test_a_child_naming_a_parameter_of_any_of_is_refused_at_depth_two() -> None:
    # AllOf takes no scope at the class-level question, so it accepts this
    # child; AnyOf above it re-asks that question at the scope question.
    inner = AllOf(opting_into("scope", _HP))
    with pytest.raises(ImproperlyConfigured, match=re.escape("AnyOf.checks[0] opts into")):
        AnyOf(inner)


def test_a_seed_a_parameter_of_another_question_is_named_for_is_accepted() -> None:
    # `scope` at the row question: AnyOf's row method takes no scope, and the
    # scope question never asks has_object_permission.
    AnyOf(opting_into("scope", _HOP), opting_into("target", _HSP))
