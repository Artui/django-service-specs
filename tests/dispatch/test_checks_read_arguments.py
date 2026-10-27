from __future__ import annotations

from typing import Any

import pytest

from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.dispatch.checks_read_arguments import checks_read_arguments
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
from tests.dispatch.utils import Record, notes_of
from tests.specs.utils import Foreign


class _Plain(PermissionCheck):
    """Answers the class question without opting into anything."""

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return True


class _OnTheClassQuestion(PermissionCheck):
    def has_permission(self, principal: Any, spec: Any, *, arguments: Any) -> bool:
        return True


class _OnTheScopeQuestion(_Plain):
    def has_scope_permission(
        self, principal: Any, spec: Any, scope: Any, *, arguments: Any
    ) -> bool:
        return True


class _OnTheObjectQuestion(_Plain):
    # Asked of a resolved row, which neither a listing nor a create has.
    def has_object_permission(self, principal: Any, spec: Any, obj: Any, *, arguments: Any) -> bool:
        return True


class _Silent(_Plain): ...


class _OnlyTheContext(PermissionCheck):
    def has_permission(self, principal: Any, spec: Any, *, call_context: Any) -> bool:
        return True


def _create(*checks: PermissionCheck) -> ServiceSpec:
    return ServiceSpec(service=Record(), permissions=list(checks))


def _on_a_row(*checks: PermissionCheck) -> ServiceSpec:
    # A target selector: its scope question is asked of the row or the set it
    # resolves, which only the call's arguments name.
    return ServiceSpec(
        service=Record(),
        permissions=list(checks),
        collection_selector_spec=SelectorSpec(kind=SelectorKind.LIST, selector=notes_of),
    )


def _listing(*checks: PermissionCheck) -> SelectorSpec:
    return SelectorSpec(kind=SelectorKind.LIST, selector=notes_of, permissions=list(checks))


@pytest.mark.parametrize("build", [_create, _on_a_row, _listing])
def test_a_check_declaring_arguments_on_the_class_question_reads_them(build: Any) -> None:
    assert checks_read_arguments(build(_OnTheClassQuestion())) is True


def test_a_check_declaring_arguments_only_on_the_scope_question_reads_them_in_a_create() -> None:
    assert checks_read_arguments(_create(_OnTheScopeQuestion())) is True


def test_the_scope_question_is_not_asked_where_a_target_or_a_selector_stands() -> None:
    # Held by name: the same check is read in a create and not beside a target
    # selector (dispatch asks a row's or a set's scope with the call's
    # arguments, not with none), and a selector spec has no scope question at all.
    assert checks_read_arguments(_on_a_row(_OnTheScopeQuestion())) is False
    assert checks_read_arguments(_listing(_OnTheScopeQuestion())) is False


@pytest.mark.parametrize("build", [_create, _on_a_row, _listing])
def test_the_object_question_is_never_asked_without_a_row(build: Any) -> None:
    assert checks_read_arguments(build(_OnTheObjectQuestion())) is False


@pytest.mark.parametrize("build", [_create, _on_a_row, _listing])
def test_checks_declaring_no_arguments_read_none(build: Any) -> None:
    assert checks_read_arguments(build(_Silent())) is False
    assert checks_read_arguments(build(_OnlyTheContext())) is False


def test_one_check_among_several_is_enough() -> None:
    assert checks_read_arguments(_create(_Silent(), _OnTheClassQuestion(), _Silent())) is True


def test_a_spec_declaring_no_permissions_has_no_checks_to_read() -> None:
    # Dispatch refuses it at the call; the reader answers about the checks it
    # has, which are none.
    assert checks_read_arguments(ServiceSpec(service=Record())) is False


def test_a_declaration_is_read_as_the_spec_it_compiles_to() -> None:
    assert checks_read_arguments(Foreign(_create(_OnTheScopeQuestion()))) is True
    assert checks_read_arguments(Foreign(_on_a_row(_OnTheScopeQuestion()))) is False


def test_a_foreign_object_with_no_spec_is_refused_as_kernel_spec_refuses_it() -> None:
    with pytest.raises(TypeError, match="as_kernel_spec"):
        checks_read_arguments(object())  # type: ignore[arg-type]
