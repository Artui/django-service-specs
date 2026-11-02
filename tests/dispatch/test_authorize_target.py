from __future__ import annotations

import dataclasses
import inspect
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.any_of import AnyOf
from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.dispatch.authorize import authorize
from django_service_specs.dispatch.authorize_target import authorize_target
from django_service_specs.dispatch.call_seeds import CallSeeds
from django_service_specs.dispatch.grant import Grant
from django_service_specs.dispatch.resolve_seeds import resolve_seeds
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.types.selector_kind import SelectorKind
from tests.authorization.utils import (
    Allow,
    Answers,
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


class _ReadsTheContext(PermissionCheck):
    """Refuses at class level, allows any row by default, and declares the call's context."""

    def __init__(self, log: list[str]) -> None:
        self.log = log

    def has_permission(self, principal: Any, spec: Any, *, call_context: Any) -> bool:
        self.log.append("owner.has_permission")
        return False


class TestAnyOf:
    """At the row question a check of ``AnyOf`` counts only where it passes the class-level one too."""

    def test_any_of_row_question_skips_a_child_refused_at_class_level(self) -> None:
        # ``owner`` refuses this principal at class level and, like most
        # checks, allows any row by default; ``staff`` admits them at class
        # level and refuses this row. Neither passes both, so the row is refused.
        log: list[str] = []
        owner = Answers("owner", log, permission=False)
        staff = Answers("staff", log, row=False)
        spec, principal = _spec([AnyOf(owner, staff)]), object()
        with pytest.raises(NotPermitted):
            authorize_target(spec, principal, object(), grant=Grant(spec, principal))
        assert log == [
            "owner.has_permission",
            "staff.has_permission",
            "staff.has_object_permission",
        ]

    def test_any_of_under_a_covering_grant_still_judges_the_row(self) -> None:
        # A grant covering the class-level question answers it without asking
        # any check, so nothing could have been remembered from it: the row
        # question asks it again.
        log: list[str] = []
        spec, principal = (
            _spec(
                [AnyOf(Answers("owner", log, permission=False), Answers("staff", log, row=False))]
            ),
            object(),
        )
        grant = authorize(spec, principal, grant=Grant(spec, principal), call_context={})
        assert log == []
        with pytest.raises(NotPermitted):
            authorize_target(spec, principal, object(), grant=grant, call_context={})
        assert "owner.has_object_permission" not in log

    def test_any_of_writes_nothing_to_the_call_s_context(self) -> None:
        # Handed the context, since a check inside it declares it, and still
        # answering the row from the questions alone: nothing a later stage,
        # or another transport's grant, could lack.
        log: list[str] = []
        context: dict[str, Any] = {}
        spec = _spec([AnyOf(_ReadsTheContext(log), Answers("staff", log, row=False))])
        principal = object()
        grant = authorize(spec, principal, call_context=context)
        with pytest.raises(NotPermitted):
            authorize_target(spec, principal, object(), grant=grant, call_context=context)
        assert context == {}
        assert log.count("owner.has_permission") == 2

    def test_a_child_passing_both_questions_passes_the_row(self) -> None:
        log: list[str] = []
        spec, principal = (
            _spec([AnyOf(Answers("owner", log, permission=False), Answers("staff", log))]),
            object(),
        )
        authorize_target(spec, principal, object(), grant=Grant(spec, principal))
        assert log[-1] == "staff.has_object_permission"

    def test_authorize_target_resolves_a_child_s_class_level_seed(self) -> None:
        # The child is asked its class-level question at the row question, so
        # the seed that question names resolves there too.
        check, principal = SeedPerQuestion(), "ada"
        spec = _spec([AnyOf(check)])
        pool_seeds, resolved = recorded_seeds()
        authorize_target(
            spec, principal, object(), grant=Grant(spec, principal), pool_seeds=pool_seeds
        )
        assert sorted(resolved) == ["club", "row_club"]
        assert check.handed == [
            ("has_permission", "club of ada"),
            ("has_object_permission", "row_club of ada"),
        ]


class TestCarriedSeeds:
    """``seeds=`` a ``CallSeeds``: taken as they are for the call it covers, refused for any other."""

    @pytest.mark.parametrize("other", ["principal", "spec", "call_context", "registry"])
    def test_a_carrier_for_another_call_is_refused_before_any_check(self, other: str) -> None:
        """Each of the four ``values_for`` is handed is held: the carrier's own would admit the call."""
        check = SeedPerQuestion()
        spec, context = _spec([check]), {}
        pool_seeds, resolved = recorded_seeds()
        carrier = resolve_seeds(spec, principal="ada", pool_seeds=pool_seeds, call_context=context)
        resolved.clear()
        principal, asked_spec = "ada", spec
        if other == "principal":
            principal = "bob"
        elif other == "spec":
            # A frozen dataclass compares by field: only identity tells the twin apart.
            asked_spec = dataclasses.replace(kernel_spec(spec))
            assert asked_spec == kernel_spec(spec)
        elif other == "call_context":
            context = {}
        else:
            pool_seeds = recorded_seeds()[0]
        with pytest.raises(NotPermitted) as refused:
            authorize_target(
                asked_spec,
                principal,
                object(),
                grant=Grant(asked_spec, principal, target_checked=True),
                seeds=carrier,
                pool_seeds=pool_seeds,
                call_context=context,
            )
        assert str(refused.value) == "The seeds do not cover this spec, principal and call context."
        assert resolved == []
        assert check.handed == []

    def test_a_carrier_is_refused_before_a_grant_that_checked_the_target_answers(self) -> None:
        spec, context = _spec([SeedPerQuestion()]), {}
        carrier = CallSeeds(spec, "ada", context, DEFAULT_POOL_SEEDS, {"row_club": "chosen"})
        with pytest.raises(NotPermitted, match="The seeds do not cover"):
            authorize_target(
                spec,
                "bob",
                object(),
                grant=Grant(spec, "bob", target_checked=True),
                seeds=carrier,
                call_context=context,
            )

    def test_a_carrier_handed_no_pool_seeds_is_matched_against_the_default_registry(self) -> None:
        check = SeedPerQuestion()
        spec, context = _spec([check]), {}
        carrier = CallSeeds(spec, "ada", context, DEFAULT_POOL_SEEDS, {"row_club": "chosen"})
        authorize_target(
            spec, "ada", object(), grant=Grant(spec, "ada"), seeds=carrier, call_context=context
        )
        assert check.handed == [("has_object_permission", "chosen")]

    def test_a_carrier_under_its_registry_resolves_nothing(self) -> None:
        """``pool_seeds=`` beside a carrier is the registry it is matched against, not a resolver."""
        check = SeedPerQuestion()
        spec, context = _spec([check]), {}
        pool_seeds, resolved = recorded_seeds()
        carrier = resolve_seeds(spec, principal="ada", pool_seeds=pool_seeds, call_context=context)
        resolved.clear()
        authorize_target(
            spec,
            "ada",
            object(),
            grant=Grant(spec, "ada"),
            seeds=carrier,
            pool_seeds=pool_seeds,
            call_context=context,
        )
        assert resolved == []
        assert check.handed == [("has_object_permission", "row_club of ada")]
        assert check.handed[0][1] is carrier.values["row_club"]

    def test_a_deactivated_principal_is_refused_though_its_carrier_covers_it(self) -> None:
        principal, check = Deactivated(), SeedPerQuestion()
        spec, context = _spec([check]), {}
        carrier = CallSeeds(spec, principal, context, DEFAULT_POOL_SEEDS, {"row_club": "chosen"})
        with pytest.raises(PrincipalUnavailable):
            authorize_target(
                spec,
                principal,
                object(),
                grant=Grant(spec, principal, target_checked=True),
                seeds=carrier,
                call_context=context,
            )
        assert check.handed == []
