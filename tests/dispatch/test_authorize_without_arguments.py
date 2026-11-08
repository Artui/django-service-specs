from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured, PermissionDenied

from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.authorization.permission_check_denied import PermissionCheckDenied
from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.dispatch.authorize_without_arguments import authorize_without_arguments
from django_service_specs.dispatch.grant import Grant
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
from tests.authorization.utils import AnswersWith, refuses
from tests.dispatch.utils import (
    Deactivated,
    Record,
    SeedPerQuestion,
    note_by_pk,
    notes_of,
    recorded_seeds,
)
from tests.specs.utils import Foreign

CLASS = "has_permission"
SCOPE = "has_scope_permission"


class _Asked(PermissionCheck):
    """Answers the class and scope questions as built, recording what each was handed.

    An answer is a bool, or an exception the question raises instead. Each
    entry is ``(question, scope, arguments, call_context)``; the class question
    has no scope, and records ``None`` there.
    """

    def __init__(self, *, permission: Any = True, scope: Any = True) -> None:
        self.answers = {CLASS: permission, SCOPE: scope}
        self.asked: list[tuple[str, Any, Any, Any]] = []

    def _answer(self, question: str) -> bool:
        answer = self.answers[question]
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def has_permission(
        self, principal: Any, spec: Any, *, arguments: Any = None, call_context: Any = None
    ) -> bool:
        self.asked.append((CLASS, None, arguments, call_context))
        return self._answer(CLASS)

    def has_scope_permission(
        self,
        principal: Any,
        spec: Any,
        scope: Any,
        *,
        arguments: Any = None,
        call_context: Any = None,
    ) -> bool:
        self.asked.append((SCOPE, scope, arguments, call_context))
        return self._answer(SCOPE)

    def questions(self) -> list[str]:
        return [question for question, *_ in self.asked]


class _ReadsTheArguments(PermissionCheck):
    """Decides by what the call names, so it cannot answer when handed nothing."""

    def has_permission(self, principal: Any, spec: Any, *, arguments: Any) -> bool:
        return arguments["owner"] == principal


class _ReadsTheArgumentsOnTheScope(PermissionCheck):
    def has_permission(self, principal: Any, spec: Any) -> bool:
        return True

    def has_scope_permission(
        self, principal: Any, spec: Any, scope: Any, *, arguments: Any
    ) -> bool:
        return arguments["owner"] == principal


def _create(*checks: PermissionCheck) -> ServiceSpec:
    return ServiceSpec(service=Record(), permissions=list(checks))


def _on_a_set(*checks: PermissionCheck) -> ServiceSpec:
    return ServiceSpec(
        service=Record(),
        permissions=list(checks),
        collection_selector_spec=SelectorSpec(kind=SelectorKind.LIST, selector=notes_of),
    )


def _on_a_row(*checks: PermissionCheck) -> ServiceSpec:
    return ServiceSpec(
        service=Record(),
        permissions=list(checks),
        instance_selector_spec=SelectorSpec(kind=SelectorKind.RETRIEVE, selector=note_by_pk),
    )


def _read(*checks: PermissionCheck) -> SelectorSpec:
    return SelectorSpec(kind=SelectorKind.LIST, selector=notes_of, permissions=list(checks))


class TestTheThreeShapes:
    """The two questions a call asks before it reads anything, for each shape of spec."""

    def test_a_create_is_asked_both_questions_of_nothing(self) -> None:
        check = _Asked()
        spec = _create(check)
        principal = object()
        granted = authorize_without_arguments(spec, principal)
        assert granted.covers(spec, principal)
        assert check.questions() == [CLASS, SCOPE]
        assert check.asked[1][1] is None

    def test_a_create_refused_on_the_scope_of_nothing_raises_the_denial(self) -> None:
        """Fails with the scope question skipped."""
        check = _Asked(scope=False)
        with pytest.raises(PermissionCheckDenied):
            authorize_without_arguments(_create(check), object())
        assert check.questions() == [CLASS, SCOPE]

    def test_a_read_is_not_asked_the_scope_of_nothing(self) -> None:
        """Fails without the predicate's first conjunct: a selector spec has no target selector to ask about."""
        check = _Asked(scope=False)
        spec = _read(check)
        principal = object()
        assert authorize_without_arguments(spec, principal).covers(spec, principal)
        assert check.questions() == [CLASS]

    @pytest.mark.parametrize("build", [_on_a_set, _on_a_row], ids=["collection", "instance"])
    def test_a_write_with_a_target_is_not_asked_the_scope_of_nothing(self, build: Any) -> None:
        """Fails without the predicate's second conjunct: its scope is a row or set only arguments name."""
        check = _Asked(scope=False)
        spec = build(check)
        principal = object()
        assert authorize_without_arguments(spec, principal).covers(spec, principal)
        assert check.questions() == [CLASS]

    @pytest.mark.parametrize("build", [_create, _on_a_set, _read])
    def test_a_refusal_on_the_class_question_raises_before_the_scope_question(
        self, build: Any
    ) -> None:
        check = _Asked(permission=False)
        with pytest.raises(PermissionCheckDenied):
            authorize_without_arguments(build(check), object())
        assert check.questions() == [CLASS]


class TestNoArguments:
    """``None``, the kernel's word for a call with none to hand, at each question."""

    def test_the_class_question_is_handed_none(self) -> None:
        check = _Asked()
        authorize_without_arguments(_read(check), object())
        assert check.asked == [(CLASS, None, None, check.asked[0][3])]
        assert check.asked[0][2] is None

    def test_the_scope_question_is_handed_none(self) -> None:
        check = _Asked()
        authorize_without_arguments(_create(check), object())
        assert check.questions() == [CLASS, SCOPE]
        assert check.asked[1][2] is None

    def test_a_check_reading_the_arguments_raises_what_it_raises(self) -> None:
        """The kernel does not read such a check as a refusal or a pass: the caller decides."""
        with pytest.raises(TypeError, match="not subscriptable"):
            authorize_without_arguments(_read(_ReadsTheArguments()), object())

    def test_a_check_reading_the_arguments_on_the_scope_raises_what_it_raises(self) -> None:
        with pytest.raises(TypeError, match="not subscriptable"):
            authorize_without_arguments(_create(_ReadsTheArgumentsOnTheScope()), object())


class TestNothingIsCaught:
    """Whatever a question raises reaches the caller as it was raised, the very object."""

    @pytest.mark.parametrize(
        "raised",
        [
            NotPermitted("The check's own refusal."),
            PermissionDenied("Django's refusal."),
            LookupError("Anything else."),
        ],
        ids=["not-permitted", "permission-denied", "arbitrary"],
    )
    @pytest.mark.parametrize("question", [CLASS, SCOPE])
    def test_a_question_s_exception_reaches_the_caller_unchanged(
        self, raised: Exception, question: str
    ) -> None:
        check = _Asked(**{"permission" if question == CLASS else "scope": raised})
        with pytest.raises(type(raised)) as caught:
            authorize_without_arguments(_create(check), object())
        assert caught.value is raised
        assert check.questions()[-1] == question

    def test_a_deactivated_principal_is_refused_before_any_check(self) -> None:
        check = _Asked()
        with pytest.raises(PrincipalUnavailable):
            authorize_without_arguments(
                _create(check), Deactivated(), pool_seeds=DEFAULT_POOL_SEEDS
            )
        assert check.asked == []

    def test_a_resolver_s_principal_unavailable_reaches_the_caller_unchanged(self) -> None:
        raised = PrincipalUnavailable()
        pool_seeds, resolved = recorded_seeds(raising=raised)
        check = SeedPerQuestion()
        with pytest.raises(PrincipalUnavailable) as caught:
            authorize_without_arguments(_create(check), object(), pool_seeds=pool_seeds)
        assert caught.value is raised
        assert resolved == ["club"]
        assert check.handed == []

    def test_a_deactivated_principal_without_pool_seeds_is_asked_as_authorize_asks_it(
        self,
    ) -> None:
        """``authorize`` refuses one only where it would resolve a seed for it."""
        check = _Asked()
        principal = Deactivated()
        spec = _create(check)
        assert authorize_without_arguments(spec, principal).covers(spec, principal)
        assert check.questions() == [CLASS, SCOPE]

    @pytest.mark.parametrize("build", [_create, _on_a_set, _read])
    def test_a_spec_declaring_no_permissions_with_no_grant_is_a_configuration_error(
        self, build: Any
    ) -> None:
        spec = dataclasses.replace(build(Unrestricted()), permissions=None)
        with pytest.raises(ImproperlyConfigured, match="declares no permissions"):
            authorize_without_arguments(spec, object())

    def test_a_check_left_awaiting_its_answer_is_a_configuration_error(self) -> None:
        with pytest.raises(ImproperlyConfigured, match="answered with an awaitable"):
            authorize_without_arguments(_create(AnswersWith(refuses())), object())


class TestPassedThrough:
    def test_both_questions_are_handed_the_one_call_context(self) -> None:
        check = _Asked()
        call_context: dict[str, Any] = {}
        authorize_without_arguments(_create(check), object(), call_context=call_context)
        assert [asked[3] for asked in check.asked] == [call_context, call_context]
        assert all(asked[3] is call_context for asked in check.asked)

    def test_a_covering_grant_answers_the_class_question_and_is_returned(self) -> None:
        check = _Asked(permission=False)
        spec = _create(check)
        principal = object()
        grant = Grant(spec, principal)
        assert authorize_without_arguments(spec, principal, grant=grant) is grant
        assert check.questions() == [SCOPE]

    def test_a_grant_that_checked_the_target_still_asks_the_scope_of_nothing(self) -> None:
        """No target is handed, so the flag covers nothing here, as in dispatch."""
        check = _Asked(scope=False)
        spec = _create(check)
        principal = object()
        grant = Grant(spec, principal, target_checked=True)
        with pytest.raises(PermissionCheckDenied):
            authorize_without_arguments(spec, principal, grant=grant)
        assert check.questions() == [SCOPE]

    def test_the_grant_returned_keeps_what_it_says(self) -> None:
        spec = _create(_Asked())
        principal = object()
        grant = Grant(spec, principal, target_checked=True)
        returned = authorize_without_arguments(spec, principal, grant=grant)
        assert returned is grant
        assert returned.target_checked is True

    def test_a_grant_for_another_principal_is_refused(self) -> None:
        check = _Asked()
        spec = _create(check)
        with pytest.raises(NotPermitted, match="does not cover"):
            authorize_without_arguments(spec, object(), grant=Grant(spec, object()))
        assert check.asked == []

    def test_a_covering_grant_on_a_spec_declaring_no_permissions_is_returned(self) -> None:
        spec = dataclasses.replace(_create(Unrestricted()), permissions=None)
        principal = object()
        grant = Grant(spec, principal)
        assert authorize_without_arguments(spec, principal, grant=grant) is grant

    def test_the_seeds_each_question_names_are_resolved_from_pool_seeds(self) -> None:
        check = SeedPerQuestion()
        pool_seeds, resolved = recorded_seeds()
        principal = "ada"
        authorize_without_arguments(_create(check), principal, pool_seeds=pool_seeds)
        assert check.handed == [
            ("has_permission", "club of ada"),
            ("has_scope_permission", "scope_club of ada"),
        ]
        assert sorted(resolved) == ["club", "scope_club"]


class TestASpecSource:
    def test_a_source_compiling_to_a_create_is_asked_the_scope_of_nothing(self) -> None:
        """Fails where the predicate reads the source rather than the spec it compiles to."""
        check = _Asked(scope=False)
        source = Foreign(compiled=_create(check))
        with pytest.raises(PermissionCheckDenied):
            authorize_without_arguments(source, object())
        assert check.questions() == [CLASS, SCOPE]

    def test_the_grant_covers_the_source_and_the_spec_it_compiles_to(self) -> None:
        spec = _create(Unrestricted())
        source = Foreign(compiled=spec)
        principal = object()
        granted = authorize_without_arguments(source, principal)
        assert granted.covers(source, principal)
        assert granted.covers(spec, principal)
