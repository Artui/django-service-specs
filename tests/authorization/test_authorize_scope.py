from __future__ import annotations

import inspect
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.authorize_scope import authorize_scope
from django_service_specs.authorization.grant import Grant
from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from tests.authorization.utils import AnswersWith, refuses
from tests.specs.utils import Foreign


class _ScopeCheck(PermissionCheck):
    """Records the scope it is asked about and refuses when told to."""

    def __init__(self, *, allow: bool = True, message: str | None = None) -> None:
        self.allow = allow
        self.message = message
        self.scopes: list[Any] = []

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return True

    def has_scope_permission(self, principal: Any, spec: Any, scope: Any) -> bool:
        self.scopes.append(scope)
        return self.allow


def _spec(permissions: list | None) -> SelectorSpec:
    return SelectorSpec(kind=SelectorKind.LIST, selector=list, permissions=permissions)


def test_the_scope_is_handed_to_every_check_as_given() -> None:
    first, second = _ScopeCheck(), _ScopeCheck()
    spec, principal, rows = _spec([first, second]), object(), [object(), object()]
    authorize_scope(spec, principal, rows, grant=Grant(spec, principal))
    assert first.scopes == [rows]
    assert second.scopes == [rows]


def test_nothing_is_a_scope_a_check_is_asked_about() -> None:
    check = _ScopeCheck()
    spec, principal = _spec([check]), object()
    authorize_scope(spec, principal, None, grant=Grant(spec, principal))
    assert check.scopes == [None]


def test_the_first_refusal_raises_with_its_own_message_and_stops_the_rest() -> None:
    refusing, after = _ScopeCheck(allow=False, message="Not this set."), _ScopeCheck()
    spec, principal = _spec([refusing, after]), object()
    with pytest.raises(NotPermitted) as excinfo:
        authorize_scope(spec, principal, [], grant=Grant(spec, principal))
    assert excinfo.value.message == "Not this set."
    assert after.scopes == []


def test_a_refusal_without_a_message_says_the_default() -> None:
    spec, principal = _spec([_ScopeCheck(allow=False)]), object()
    with pytest.raises(NotPermitted) as excinfo:
        authorize_scope(spec, principal, [], grant=Grant(spec, principal))
    assert excinfo.value.message == NotPermitted.default_message


def test_a_grant_that_checked_the_target_skips_the_checks() -> None:
    check = _ScopeCheck(allow=False)
    spec, principal = _spec([check]), object()
    authorize_scope(spec, principal, [], grant=Grant(spec, principal, target_checked=True))
    assert check.scopes == []


def test_no_permissions_declared_has_nothing_to_check() -> None:
    spec, principal = _spec(None), object()
    authorize_scope(spec, principal, [], grant=Grant(spec, principal))


def test_a_check_answering_with_a_coroutine_is_refused_rather_than_read_as_a_pass() -> None:
    # Sync-only like the class-level check: an unawaited answer is truthy.
    answer = refuses()
    spec, principal = _spec([AnswersWith(answer)]), object()
    with pytest.raises(ImproperlyConfigured, match="answered with an awaitable") as caught:
        authorize_scope(spec, principal, None, grant=Grant(spec, principal))
    assert "AnswersWith.has_scope_permission" in str(caught.value)
    assert inspect.getcoroutinestate(answer) == inspect.CORO_CLOSED


def test_a_source_s_scope_checks_are_the_spec_it_compiles_to_s() -> None:
    check = _ScopeCheck(allow=False, message="Not this set.")
    source, principal = Foreign(_spec([check])), object()

    with pytest.raises(NotPermitted, match="Not this set."):
        authorize_scope(source, principal, ["row"], grant=Grant(source, principal))
    assert check.scopes == [["row"]]
