from __future__ import annotations

import inspect
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.dispatch.authorize_target import authorize_target
from django_service_specs.dispatch.grant import Grant
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.types.selector_kind import SelectorKind
from tests.authorization.utils import (
    Allow,
    AnswersWith,
    Refuse,
    RefuseWithMessage,
    SeesTheCall,
    refuses,
)
from tests.dispatch.utils import (
    Arguing,
    Deactivated,
    Offered,
    PositionalOnly,
    SeedPerQuestion,
    recorded_seeds,
)
from tests.specs.utils import Foreign


def _spec(permissions: list | None) -> SelectorSpec:
    return SelectorSpec(kind=SelectorKind.RETRIEVE, selector=list, permissions=permissions)


def test_skips_the_checks_when_the_grant_already_checked_the_target() -> None:
    check = Allow()
    spec, principal, target = _spec([check]), object(), object()
    grant = Grant(spec, principal, target_checked=True)
    authorize_target(spec, principal, target, grant=grant)
    assert check.object_level_calls == 0


def test_no_permissions_declared_has_nothing_to_check() -> None:
    # Called directly: dispatch hands authorize_target the spec it dispatched,
    # never a nested selector, and authorize() refuses one whose permissions
    # are None before any target is resolved. Nothing to check reads as pass,
    # not refuse.
    spec, principal, target = _spec(None), object(), object()
    grant = Grant(spec, principal)
    authorize_target(spec, principal, target, grant=grant)


def test_a_refusal_raises_not_permitted_with_the_default_message() -> None:
    spec, principal, target = _spec([Refuse()]), object(), object()
    grant = Grant(spec, principal)
    with pytest.raises(NotPermitted) as excinfo:
        authorize_target(spec, principal, target, grant=grant)
    assert excinfo.value.message == NotPermitted.default_message


def test_a_refusal_raises_not_permitted_with_the_checks_own_message() -> None:
    spec, principal, target = _spec([RefuseWithMessage()]), object(), object()
    grant = Grant(spec, principal)
    with pytest.raises(NotPermitted, match="Staff only."):
        authorize_target(spec, principal, target, grant=grant)


def test_checks_run_in_order_and_stop_at_the_first_refusal() -> None:
    later = Allow()
    spec, principal, target = _spec([Refuse(), later]), object(), object()
    grant = Grant(spec, principal)
    with pytest.raises(NotPermitted):
        authorize_target(spec, principal, target, grant=grant)
    assert later.object_level_calls == 0


@pytest.mark.parametrize("count", [pytest.param(1, id="one"), pytest.param(2, id="two")])
def test_every_check_runs_when_all_pass(count: int) -> None:
    checks = [Allow() for _ in range(count)]
    spec, principal, target = _spec(checks), object(), object()
    grant = Grant(spec, principal)
    authorize_target(spec, principal, target, grant=grant)
    assert [check.object_level_calls for check in checks] == [1] * count


def test_unrestricted_allows_at_the_object_level_too() -> None:
    spec, principal, target = _spec([Unrestricted()]), object(), object()
    grant = Grant(spec, principal)
    authorize_target(spec, principal, target, grant=grant)


def test_a_check_answering_with_a_coroutine_is_refused_rather_than_read_as_a_pass() -> None:
    # Sync-only like the class-level check: an unawaited answer is truthy.
    answer = refuses()
    spec, principal = _spec([AnswersWith(answer)]), object()
    with pytest.raises(ImproperlyConfigured, match="answered with an awaitable") as caught:
        authorize_target(spec, principal, object(), grant=Grant(spec, principal))
    assert "AnswersWith.has_object_permission" in str(caught.value)
    assert inspect.getcoroutinestate(answer) == inspect.CORO_CLOSED


def test_a_source_s_object_checks_are_the_spec_it_compiles_to_s() -> None:
    source, principal = Foreign(_spec([RefuseWithMessage()])), object()

    with pytest.raises(NotPermitted, match="Staff only."):
        authorize_target(source, principal, object(), grant=Grant(source, principal))


def test_a_source_s_grant_that_checked_the_target_skips_the_checks() -> None:
    check = Allow()
    source, principal = Foreign(_spec([check])), object()

    authorize_target(
        source, principal, object(), grant=Grant(source, principal, target_checked=True)
    )

    assert check.object_level_calls == 0


def test_a_check_declaring_arguments_is_handed_them_as_given_and_none_without() -> None:
    arguing, legacy = Arguing(), Allow()
    spec, principal, arguments = _spec([arguing, legacy]), object(), {"pk": 1}
    authorize_target(spec, principal, object(), grant=Grant(spec, principal), arguments=arguments)
    authorize_target(spec, principal, object(), grant=Grant(spec, principal))
    assert arguing.asked == [("has_object_permission", arguments), ("has_object_permission", None)]


PRINCIPAL = object()


def test_a_check_is_offered_the_call_context_and_the_seeds_it_names() -> None:
    check = Offered()
    spec = SelectorSpec(kind=SelectorKind.LIST, selector=list, permissions=[check])
    context: dict[str, Any] = {}
    authorize_target(
        spec,
        PRINCIPAL,
        object(),
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
        authorize_target(
            spec, PRINCIPAL, object(), grant=Grant(spec, PRINCIPAL), seeds={"tenant": "acme"}
        )
    (_, first, _), (_, second, _) = check.asked
    assert first == second == {}
    assert first is not second


class TestPoolSeeds:
    """``pool_seeds=`` resolves the seeds ``has_object_permission`` names, and no other."""

    def test_the_seed_its_question_names_is_resolved_for_it(self) -> None:
        check, principal = SeedPerQuestion(), "ada"
        spec = _spec([check])
        pool_seeds, resolved = recorded_seeds()
        authorize_target(
            spec, principal, object(), grant=Grant(spec, principal), pool_seeds=pool_seeds
        )
        assert check.handed == [("has_object_permission", "row_club of ada")]
        assert resolved == ["row_club"]

    def test_a_grant_that_checked_the_target_resolves_no_seed(self) -> None:
        check, principal = SeedPerQuestion(), "ada"
        spec = _spec([check])
        pool_seeds, resolved = recorded_seeds()
        grant = Grant(spec, principal, target_checked=True)
        authorize_target(spec, principal, object(), grant=grant, pool_seeds=pool_seeds)
        assert resolved == []

    def test_seeds_and_pool_seeds_together_are_refused(self) -> None:
        check, principal = SeedPerQuestion(), "ada"
        spec = _spec([check])
        pool_seeds, resolved = recorded_seeds()
        with pytest.raises(TypeError, match=r"seeds= or pool_seeds=, not both"):
            authorize_target(
                spec,
                principal,
                object(),
                grant=Grant(spec, principal),
                seeds={"row_club": "chosen"},
                pool_seeds=pool_seeds,
            )
        assert resolved == []

    def test_a_call_without_pool_seeds_asks_a_seed_naming_check_as_before(self) -> None:
        check, principal = SeedPerQuestion(), "ada"
        spec = _spec([check])
        with pytest.raises(TypeError) as raised:
            authorize_target(spec, principal, object(), grant=Grant(spec, principal))
        assert str(raised.value).endswith(
            "has_object_permission() missing 1 required keyword-only argument: 'row_club'"
        )
        assert check.handed == []

    def test_both_kinds_are_refused_though_the_grant_checked_the_target(self) -> None:
        """Unconditionally: below the ``target_checked`` short cut this call would return."""
        spec, principal = _spec([SeedPerQuestion()]), "ada"
        pool_seeds, resolved = recorded_seeds()
        with pytest.raises(TypeError) as raised:
            authorize_target(
                spec,
                principal,
                object(),
                grant=Grant(spec, principal, target_checked=True),
                seeds={"row_club": "chosen"},
                pool_seeds=pool_seeds,
            )
        assert str(raised.value) == (
            "authorize_target() takes seeds= or pool_seeds=, not both: seeds= are values already "
            "resolved and pool_seeds= resolves them, so one would silently outrank the other."
        )
        assert resolved == []

    def test_a_deactivated_principal_resolves_no_seed(self) -> None:
        principal, check = Deactivated(), SeedPerQuestion()
        spec = _spec([check])
        pool_seeds, resolved = recorded_seeds()
        with pytest.raises(PrincipalUnavailable):
            authorize_target(
                spec, principal, object(), grant=Grant(spec, principal), pool_seeds=pool_seeds
            )
        assert resolved == []
        assert check.handed == []

    def test_a_deactivated_principal_is_refused_though_the_grant_checked_the_target(self) -> None:
        principal = Deactivated()
        spec = _spec([SeedPerQuestion()])
        pool_seeds, resolved = recorded_seeds()
        grant = Grant(spec, principal, target_checked=True)
        with pytest.raises(PrincipalUnavailable):
            authorize_target(spec, principal, object(), grant=grant, pool_seeds=pool_seeds)
        assert resolved == []

    def test_a_deactivated_principal_without_pool_seeds_is_asked_as_before(self) -> None:
        """Fails without the ``pool_seeds is not None`` conjunct of the guard."""
        principal, check = Deactivated(), Allow()
        spec = _spec([check])
        authorize_target(spec, principal, object(), grant=Grant(spec, principal))
        assert check.object_level_calls == 1

    def test_a_positional_parameter_named_like_a_seed_is_not_one(self) -> None:
        """``OBJECT_LEVEL`` counts three: ``row_club`` here is the target, not a seed."""
        check, principal, target = PositionalOnly(), "ada", object()
        spec = _spec([check])
        pool_seeds, resolved = recorded_seeds()
        authorize_target(
            spec, principal, target, grant=Grant(spec, principal), pool_seeds=pool_seeds
        )
        assert resolved == []
        assert check.handed == [("has_object_permission", target)]


def test_a_check_is_handed_the_context_s_request_and_view() -> None:
    check, request, view = SeesTheCall(), object(), object()
    spec, principal = _spec([check]), object()
    authorize_target(
        spec,
        principal,
        object(),
        grant=Grant(spec, principal),
        call_context={"request": request, "view": view},
    )
    assert check.seen == [("has_object_permission", request, view)]
