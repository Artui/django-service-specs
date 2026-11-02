from __future__ import annotations

import re
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.all_of import AllOf
from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.types.selector_kind import SelectorKind
from tests.authorization.utils import Allow, Answers, opting_into

_PRINCIPAL, _SPEC, _ROW = object(), object(), object()


def _ask(check: PermissionCheck, method: str) -> Any:
    """Ask ``check`` one question as an ``authorize`` function would, with nothing offered."""
    if method == "has_permission":
        return check.has_permission(_PRINCIPAL, _SPEC)
    return getattr(check, method)(_PRINCIPAL, _SPEC, _ROW)


_QUESTIONS = pytest.mark.parametrize(
    ("method", "refusing"),
    [
        ("has_permission", {"permission": False}),
        ("has_object_permission", {"row": False}),
        ("has_scope_permission", {"scope": False}),
    ],
)


@_QUESTIONS
def test_all_of_passes_when_every_check_passes(method: str, refusing: dict[str, Any]) -> None:
    log: list[str] = []
    check = AllOf(Answers("a", log), Answers("b", log))
    assert _ask(check, method) is True
    assert log == [f"a.{method}", f"b.{method}"]


@_QUESTIONS
def test_all_of_does_not_ask_past_the_first_refusal(method: str, refusing: dict[str, Any]) -> None:
    log: list[str] = []
    check = AllOf(Answers("a", log, **refusing), Answers("b", log))
    assert _ask(check, method) is False
    assert log == [f"a.{method}"]


def test_the_message_is_the_one_it_was_built_with() -> None:
    assert AllOf(Allow(), message="Staff in this tenant.").message == "Staff in this tenant."
    assert AllOf(Allow()).message is None


def test_its_checks_are_kept_in_order() -> None:
    first, second = Allow(), Allow()
    assert AllOf(first, second).checks == (first, second)


def test_an_empty_combinator_is_refused() -> None:
    # Every check passing is vacuously true of none, so an empty AllOf would
    # let anyone run the operation it guards.
    with pytest.raises(ImproperlyConfigured, match=r"AllOf\.checks is empty"):
        AllOf()


class _AsyncClassLevel(PermissionCheck):
    async def has_permission(self, principal: Any, spec: Any) -> bool:
        return False


class _AsyncObjectLevel(PermissionCheck):
    def has_permission(self, principal: Any, spec: Any) -> bool:
        return True

    async def has_object_permission(self, principal: Any, spec: Any, target: Any) -> bool:
        return False


class _AsyncScopeLevel(PermissionCheck):
    def has_permission(self, principal: Any, spec: Any) -> bool:
        return True

    async def has_scope_permission(self, principal: Any, spec: Any, scope: Any) -> bool:
        return False


class TestAChildIsRefused:
    """A child is held to the rule a spec's ``permissions=`` holds a check to, worded for the combinator."""

    def test_a_class(self) -> None:
        with pytest.raises(
            ImproperlyConfigured,
            match=re.escape("AllOf.checks holds the class Allow; pass an instance, Allow()."),
        ):
            AllOf(Allow(), Allow)  # ty: ignore[invalid-argument-type]

    def test_something_that_is_not_a_check(self) -> None:
        with pytest.raises(
            ImproperlyConfigured,
            match=re.escape("AllOf.checks holds str, which is not a PermissionCheck."),
        ):
            AllOf(Allow(), "IsStaff")  # ty: ignore[invalid-argument-type]

    # One case per method, since coverage cannot see a name dropped from the
    # questions the rule reads.
    @pytest.mark.parametrize(
        ("check", "method"),
        [
            (_AsyncClassLevel(), "has_permission"),
            (_AsyncObjectLevel(), "has_object_permission"),
            (_AsyncScopeLevel(), "has_scope_permission"),
        ],
    )
    def test_an_async_def_method(self, check: PermissionCheck, method: str) -> None:
        named = f"AllOf.checks[1].{method} is {type(check).__name__}.{method}, an async callable"
        with pytest.raises(ImproperlyConfigured, match=re.escape(named)):
            AllOf(Allow(), check)


_HP, _HOP, _HSP = "has_permission", "has_object_permission", "has_scope_permission"


@pytest.mark.parametrize(
    ("asked", "name"),
    [
        (_HP, "principal"),
        (_HP, "spec"),
        (_HOP, "principal"),
        (_HOP, "spec"),
        (_HOP, "target"),
        (_HSP, "principal"),
        (_HSP, "spec"),
        (_HSP, "scope"),
    ],
)
def test_a_child_naming_a_parameter_of_all_of_is_refused(asked: str, name: str) -> None:
    named = (
        f"AllOf.checks[1] opts into a seed named '{name}' at {asked}, and "
        f"AllOf.{asked} takes {name} itself, so a seed of that name cannot reach "
        "the child through it. Rename the keyword."
    )
    with pytest.raises(ImproperlyConfigured, match=re.escape(named)):
        AllOf(Allow(), opting_into(name, asked))


def test_a_child_naming_a_parameter_of_all_of_is_refused_at_depth_two() -> None:
    with pytest.raises(ImproperlyConfigured, match=re.escape("AllOf.checks[0] opts into")):
        AllOf(AllOf(opting_into("scope", _HSP)))


class _ScopeSeedAtClassLevel(PermissionCheck):
    def has_permission(self, principal: Any, spec: Any, *, scope: Any) -> bool:
        return scope == "seeded"


def test_a_seed_named_for_another_question_s_parameter_is_accepted_and_reaches_the_child() -> None:
    # AllOf asks has_permission at the class-level question alone, which
    # takes no scope, so the seed is handed through (and AnyOf, re-asking it
    # at the scope question, would refuse the same child).
    seeds = DEFAULT_POOL_SEEDS.extend(scope=lambda *, user: "seeded")
    spec = SelectorSpec(
        kind=SelectorKind.LIST,
        selector=lambda: [1, 2],
        permissions=[AllOf(_ScopeSeedAtClassLevel())],
    )
    assert dispatch(spec, principal=object(), arguments={}, pool_seeds=seeds).value == [1, 2]
    other = DEFAULT_POOL_SEEDS.extend(scope=lambda *, user: "other")
    with pytest.raises(NotPermitted):
        dispatch(spec, principal=object(), arguments={}, pool_seeds=other)
