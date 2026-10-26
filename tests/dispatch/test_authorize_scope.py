from __future__ import annotations

import inspect
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.dispatch.authorize_scope import authorize_scope
from django_service_specs.dispatch.grant import Grant
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.types.selector_kind import SelectorKind
from tests.authorization.utils import AnswersWith, refuses
from tests.dispatch.utils import (
    Arguing,
    Deactivated,
    Offered,
    PositionalOnly,
    SeedPerQuestion,
    recorded_seeds,
)
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


def test_a_check_declaring_arguments_is_handed_them_as_given_and_none_without() -> None:
    arguing, legacy = Arguing(), _ScopeCheck()
    spec, principal, arguments = _spec([arguing, legacy]), object(), {"pk": 1}
    authorize_scope(spec, principal, None, grant=Grant(spec, principal), arguments=arguments)
    authorize_scope(spec, principal, None, grant=Grant(spec, principal))
    assert arguing.asked == [("has_scope_permission", arguments), ("has_scope_permission", None)]


PRINCIPAL = object()


def test_a_check_is_offered_the_call_context_and_the_seeds_it_names() -> None:
    check = Offered()
    spec = SelectorSpec(kind=SelectorKind.LIST, selector=list, permissions=[check])
    context: dict[str, Any] = {}
    authorize_scope(
        spec,
        PRINCIPAL,
        None,
        grant=Grant(spec, PRINCIPAL),
        call_context=context,
        seeds={"tenant": "acme"},
    )
    ((_, handed, tenant),) = check.asked
    assert handed is context
    assert tenant == "acme"


def test_a_check_asked_with_no_call_context_gets_a_dict_of_its_own() -> None:
    check = Offered()
    spec = SelectorSpec(kind=SelectorKind.LIST, selector=list, permissions=[check])
    for _ in range(2):
        authorize_scope(
            spec, PRINCIPAL, None, grant=Grant(spec, PRINCIPAL), seeds={"tenant": "acme"}
        )
    (_, first, _), (_, second, _) = check.asked
    assert first == second == {}
    assert first is not second


class TestPoolSeeds:
    """``pool_seeds=`` resolves the seeds ``has_scope_permission`` names, and no other."""

    def test_the_seed_its_question_names_is_resolved_for_it(self) -> None:
        check, principal = SeedPerQuestion(), "ada"
        spec = _spec([check])
        pool_seeds, resolved = recorded_seeds()
        authorize_scope(spec, principal, None, grant=Grant(spec, principal), pool_seeds=pool_seeds)
        assert check.handed == [("has_scope_permission", "scope_club of ada")]
        assert resolved == ["scope_club"]

    def test_a_grant_that_checked_the_target_resolves_no_seed(self) -> None:
        check, principal = SeedPerQuestion(), "ada"
        spec = _spec([check])
        pool_seeds, resolved = recorded_seeds()
        grant = Grant(spec, principal, target_checked=True)
        authorize_scope(spec, principal, None, grant=grant, pool_seeds=pool_seeds)
        assert resolved == []

    def test_seeds_and_pool_seeds_together_are_refused(self) -> None:
        check, principal = SeedPerQuestion(), "ada"
        spec = _spec([check])
        pool_seeds, resolved = recorded_seeds()
        with pytest.raises(TypeError, match=r"seeds= or pool_seeds=, not both"):
            authorize_scope(
                spec,
                principal,
                None,
                grant=Grant(spec, principal),
                seeds={"scope_club": "chosen"},
                pool_seeds=pool_seeds,
            )
        assert resolved == []

    def test_a_call_without_pool_seeds_asks_a_seed_naming_check_as_before(self) -> None:
        check, principal = SeedPerQuestion(), "ada"
        spec = _spec([check])
        with pytest.raises(TypeError) as raised:
            authorize_scope(spec, principal, None, grant=Grant(spec, principal))
        assert str(raised.value).endswith(
            "has_scope_permission() missing 1 required keyword-only argument: 'scope_club'"
        )
        assert check.handed == []

    def test_both_kinds_are_refused_though_the_grant_checked_the_target(self) -> None:
        """Unconditionally: below the ``target_checked`` short cut this call would return."""
        spec, principal = _spec([SeedPerQuestion()]), "ada"
        pool_seeds, resolved = recorded_seeds()
        with pytest.raises(TypeError) as raised:
            authorize_scope(
                spec,
                principal,
                None,
                grant=Grant(spec, principal, target_checked=True),
                seeds={"scope_club": "chosen"},
                pool_seeds=pool_seeds,
            )
        assert str(raised.value) == (
            "authorize_scope() takes seeds= or pool_seeds=, not both: seeds= are values already "
            "resolved and pool_seeds= resolves them, so one would silently outrank the other."
        )
        assert resolved == []

    def test_a_deactivated_principal_resolves_no_seed(self) -> None:
        principal, check = Deactivated(), SeedPerQuestion()
        spec = _spec([check])
        pool_seeds, resolved = recorded_seeds()
        with pytest.raises(PrincipalUnavailable):
            authorize_scope(
                spec, principal, None, grant=Grant(spec, principal), pool_seeds=pool_seeds
            )
        assert resolved == []
        assert check.handed == []

    def test_a_deactivated_principal_is_refused_though_the_grant_checked_the_target(self) -> None:
        principal = Deactivated()
        spec = _spec([SeedPerQuestion()])
        pool_seeds, resolved = recorded_seeds()
        grant = Grant(spec, principal, target_checked=True)
        with pytest.raises(PrincipalUnavailable):
            authorize_scope(spec, principal, None, grant=grant, pool_seeds=pool_seeds)
        assert resolved == []

    def test_a_deactivated_principal_without_pool_seeds_is_asked_as_before(self) -> None:
        """Fails without the ``pool_seeds is not None`` conjunct of the guard."""
        principal, check = Deactivated(), _ScopeCheck()
        spec = _spec([check])
        authorize_scope(spec, principal, None, grant=Grant(spec, principal))
        assert check.scopes == [None]

    def test_a_positional_parameter_named_like_a_seed_is_not_one(self) -> None:
        """``SCOPE_LEVEL`` counts three: ``scope_club`` here is the scope, not a seed."""
        check, principal, scope = PositionalOnly(), "ada", object()
        spec = _spec([check])
        pool_seeds, resolved = recorded_seeds()
        authorize_scope(spec, principal, scope, grant=Grant(spec, principal), pool_seeds=pool_seeds)
        assert resolved == []
        assert check.handed == [("has_scope_permission", scope)]
