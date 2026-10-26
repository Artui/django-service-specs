from __future__ import annotations

import inspect
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.dispatch.adispatch import adispatch
from django_service_specs.dispatch.authorize import authorize
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.grant import Grant
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
from tests.authorization.utils import (
    Allow,
    AnswersWith,
    NotACoroutine,
    Refuse,
    RefuseWithMessage,
    SeesTheCall,
    refuses,
    refuses_lazily,
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
    return SelectorSpec(kind=SelectorKind.LIST, selector=list, permissions=permissions)


def test_a_covering_grant_is_returned_as_is() -> None:
    spec, principal = _spec([Unrestricted()]), object()
    grant = Grant(spec, principal)
    assert authorize(spec, principal, grant=grant) is grant


def test_a_non_covering_grant_raises_not_permitted() -> None:
    spec, principal = _spec([Unrestricted()]), object()
    other_grant = Grant(_spec([Unrestricted()]), principal)
    with pytest.raises(NotPermitted, match="does not cover"):
        authorize(spec, principal, grant=other_grant)


def test_no_grant_and_no_declared_permissions_raises_improperly_configured() -> None:
    spec, principal = _spec(None), object()
    with pytest.raises(
        ImproperlyConfigured, match=r"(?s)for .* declares no permissions.*Unrestricted"
    ):
        authorize(spec, principal)


def test_no_grant_and_a_passing_check_returns_a_fresh_grant() -> None:
    spec, principal = _spec([Unrestricted()]), object()
    grant = authorize(spec, principal)
    assert isinstance(grant, Grant)
    assert grant.covers(spec, principal)
    assert grant.target_checked is False


def test_a_refusal_raises_not_permitted_with_the_default_message() -> None:
    spec, principal = _spec([Refuse()]), object()
    with pytest.raises(NotPermitted) as excinfo:
        authorize(spec, principal)
    assert excinfo.value.message == NotPermitted.default_message


def test_a_refusal_raises_not_permitted_with_the_checks_own_message() -> None:
    spec, principal = _spec([RefuseWithMessage()]), object()
    with pytest.raises(NotPermitted, match="Staff only."):
        authorize(spec, principal)


def test_checks_run_in_order_and_stop_at_the_first_refusal() -> None:
    later = Allow()
    spec, principal = _spec([Refuse(), later]), object()
    with pytest.raises(NotPermitted):
        authorize(spec, principal)
    assert later.class_level_calls == 0


def test_every_check_runs_when_all_pass() -> None:
    first, second = Allow(), Allow()
    spec, principal = _spec([first, second]), object()
    authorize(spec, principal)
    assert first.class_level_calls == 1
    assert second.class_level_calls == 1


class TestAnAnswerThatIsNotAnAnswer:
    """A check is sync-only, and an unawaited answer is truthy: refused, never read as a pass.

    Every check here is a plain ``def`` returning the object, the shape a spec
    cannot refuse at construction, so the refusal comes from where the answer
    is read. Each shape holds one condition of that guard.
    """

    def test_a_coroutine_is_refused_and_closed(self) -> None:
        answer = refuses()
        spec = _spec([AnswersWith(answer)])
        with pytest.raises(ImproperlyConfigured, match="answered with an awaitable") as caught:
            authorize(spec, object())
        assert "AnswersWith.has_permission" in str(caught.value)
        # Not the construction refusal: the spec was accepted, and this is the read.
        assert "an async callable" not in str(caught.value)
        # Closed, so nothing is left to warn that it was never awaited.
        assert inspect.getcoroutinestate(answer) == inspect.CORO_CLOSED

    def test_an_awaitable_that_is_not_a_coroutine_is_refused(self) -> None:
        spec = _spec([AnswersWith(NotACoroutine())])
        with pytest.raises(ImproperlyConfigured, match="answered with an awaitable"):
            authorize(spec, object())

    def test_an_async_generator_is_refused(self) -> None:
        # Not awaitable, so ``isawaitable`` alone would let it through as true.
        answer = refuses_lazily()
        spec = _spec([AnswersWith(answer)])
        with pytest.raises(ImproperlyConfigured, match="answered with an awaitable"):
            authorize(spec, object())

    def test_the_checks_after_it_are_not_asked(self) -> None:
        answer, after = refuses(), Allow()
        with pytest.raises(ImproperlyConfigured):
            authorize(_spec([AnswersWith(answer), after]), object())
        assert after.class_level_calls == 0


@pytest.mark.django_db
def test_dispatch_does_not_run_a_service_its_check_answered_with_a_coroutine() -> None:
    ran: list[Any] = []

    def service() -> None:
        ran.append(True)

    answer = refuses()
    spec = ServiceSpec(service=service, permissions=[AnswersWith(answer)])
    with pytest.raises(ImproperlyConfigured, match="answered with an awaitable"):
        dispatch(spec, principal=object(), arguments={})
    assert ran == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("atomic", [True, False], ids=["atomic", "non-atomic"])
async def test_adispatch_does_not_run_a_service_its_check_answered_with_a_coroutine(
    atomic: bool,
) -> None:
    # An ``async def`` service, so both of adispatch's paths are walked: run
    # inside the hop when atomic, awaited after it when not. The check is
    # answered inside the hop either way, and the refusal must land first.
    ran: list[Any] = []

    async def service() -> None:
        ran.append(True)

    answer = refuses()
    spec = ServiceSpec(service=service, permissions=[AnswersWith(answer)], atomic=atomic)
    with pytest.raises(ImproperlyConfigured, match="answered with an awaitable"):
        await adispatch(spec, principal=object(), arguments={})
    assert ran == []
    assert inspect.getcoroutinestate(answer) == inspect.CORO_CLOSED


def test_a_source_is_authorized_as_the_spec_it_compiles_to() -> None:
    asked: list[Any] = []

    class Recording(Unrestricted):
        def has_permission(self, principal: Any, spec: Any) -> bool:
            asked.append(spec)
            return True

    source, principal = Foreign(_spec([Recording()])), object()
    grant = authorize(source, principal)

    # The check is asked about the compiled spec, the one dispatch hands it.
    assert asked == [kernel_spec(source)]
    assert asked[0] is kernel_spec(source)
    assert grant.covers(source, principal)


def test_a_source_s_grant_is_honoured_for_the_source() -> None:
    source, principal = Foreign(_spec([Refuse()])), object()
    grant = Grant(source, principal)

    assert authorize(source, principal, grant=grant) is grant
    assert authorize(kernel_spec(source), principal, grant=grant) is grant


def test_a_check_declaring_arguments_is_handed_them_as_given_and_none_without() -> None:
    arguing, legacy = Arguing(), Allow()
    spec, principal, arguments = _spec([arguing, legacy]), object(), {"pk": 1}
    authorize(spec, principal, arguments=arguments)
    authorize(spec, principal)
    assert arguing.asked == [("has_permission", arguments), ("has_permission", None)]


PRINCIPAL = object()


def test_a_check_is_offered_the_call_context_and_the_seeds_it_names() -> None:
    check = Offered()
    spec = SelectorSpec(kind=SelectorKind.LIST, selector=list, permissions=[check])
    context: dict[str, Any] = {}
    authorize(spec, PRINCIPAL, call_context=context, seeds={"tenant": "acme"})
    ((_, handed, tenant),) = check.asked
    assert handed is context
    assert tenant == "acme"


def test_a_check_asked_with_no_call_context_gets_a_dict_of_its_own() -> None:
    check = Offered()
    spec = SelectorSpec(kind=SelectorKind.LIST, selector=list, permissions=[check])
    for _ in range(2):
        authorize(spec, PRINCIPAL, seeds={"tenant": "acme"})
    (_, first, _), (_, second, _) = check.asked
    assert first == second == {}
    assert first is not second


def test_a_seed_left_out_of_seeds_is_not_offered() -> None:
    """A check naming a seed nobody resolved is asked without it, and its
    own signature decides: here, a required keyword, so a ``TypeError``."""
    spec = SelectorSpec(kind=SelectorKind.LIST, selector=list, permissions=[Offered()])
    with pytest.raises(TypeError, match="tenant"):
        authorize(spec, PRINCIPAL)


class TestPoolSeeds:
    """``pool_seeds=`` resolves the seeds the class-level check names, and no other."""

    def test_the_seed_the_class_level_check_names_is_resolved_for_it(self) -> None:
        check = SeedPerQuestion()
        pool_seeds, resolved = recorded_seeds()
        authorize(_spec([check]), "ada", pool_seeds=pool_seeds)
        assert check.handed == [("has_permission", "club of ada")]
        # Not a seed only the object or scope question names, and not one no
        # check names at all: either could read what a refused caller lacks.
        assert resolved == ["club"]

    def test_a_spec_whose_checks_name_no_seed_resolves_none(self) -> None:
        pool_seeds, resolved = recorded_seeds()
        authorize(_spec([Unrestricted()]), "ada", pool_seeds=pool_seeds)
        assert resolved == []

    def test_a_covering_grant_resolves_no_seed(self) -> None:
        check, principal = SeedPerQuestion(), "ada"
        spec = _spec([check])
        pool_seeds, resolved = recorded_seeds()
        grant = Grant(spec, principal)
        assert authorize(spec, principal, grant=grant, pool_seeds=pool_seeds) is grant
        assert resolved == []
        assert check.handed == []

    def test_seeds_and_pool_seeds_together_are_refused(self) -> None:
        pool_seeds, resolved = recorded_seeds()
        with pytest.raises(TypeError, match=r"seeds= or pool_seeds=, not both"):
            authorize(
                _spec([SeedPerQuestion()]), "ada", seeds={"club": "chosen"}, pool_seeds=pool_seeds
            )
        assert resolved == []

    def test_a_seed_raising_principal_unavailable_ends_the_call_before_its_check(self) -> None:
        check = SeedPerQuestion()
        pool_seeds, _ = recorded_seeds(raising=PrincipalUnavailable())
        with pytest.raises(PrincipalUnavailable):
            authorize(_spec([check]), "ada", pool_seeds=pool_seeds)
        assert check.handed == []

    def test_a_named_seed_left_unregistered_is_not_offered(self) -> None:
        """As with ``seeds=``: the check's own signature decides, here a ``TypeError``."""
        with pytest.raises(TypeError, match="club"):
            authorize(_spec([SeedPerQuestion()]), "ada", pool_seeds=DEFAULT_POOL_SEEDS)

    def test_a_call_without_pool_seeds_asks_a_seed_naming_check_as_before(self) -> None:
        """A transport calling ``authorize(spec, principal)`` - django-spec-html's page
        does - is asked exactly as before ``pool_seeds`` existed: the check is handed
        no seed, and its own signature refuses the call."""
        check = SeedPerQuestion()
        with pytest.raises(TypeError) as raised:
            authorize(_spec([check]), "ada")
        assert str(raised.value).endswith(
            "has_permission() missing 1 required keyword-only argument: 'club'"
        )
        assert check.handed == []

    def test_a_dispatch_after_it_resolves_the_named_seed_again(self) -> None:
        """The values are not carried on the grant, as the docs say."""
        check, principal = SeedPerQuestion(), "ada"
        spec = _spec([check])
        pool_seeds, resolved = recorded_seeds()
        grant = authorize(spec, principal, pool_seeds=pool_seeds)
        dispatch(spec, principal=principal, arguments={}, grant=grant, pool_seeds=pool_seeds)
        # Once for authorize, and once for dispatch's own call.
        assert resolved.count("club") == 2
        # The grant stood in for dispatch's class-level check: it was asked once.
        assert [asked for asked in check.handed if asked[0] == "has_permission"] == [
            ("has_permission", "club of ada")
        ]

    def test_both_kinds_are_refused_before_a_covering_grant_answers(self) -> None:
        """Unconditionally, as documented: not only when a check is asked.

        Holds the refusal's place at the top of the function: below the grant's
        short cut, this call would return the grant.
        """
        spec, principal = _spec([SeedPerQuestion()]), "ada"
        pool_seeds, resolved = recorded_seeds()
        with pytest.raises(TypeError) as raised:
            authorize(
                spec,
                principal,
                grant=Grant(spec, principal),
                seeds={"club": "chosen"},
                pool_seeds=pool_seeds,
            )
        assert str(raised.value) == (
            "authorize() takes seeds= or pool_seeds=, not both: seeds= are values already "
            "resolved and pool_seeds= resolves them, so one would silently outrank the other."
        )
        assert resolved == []

    def test_a_deactivated_principal_resolves_no_seed(self) -> None:
        """Dispatch refuses one before any resolver runs, so this does."""
        check = SeedPerQuestion()
        pool_seeds, resolved = recorded_seeds()
        with pytest.raises(PrincipalUnavailable):
            authorize(_spec([check]), Deactivated(), pool_seeds=pool_seeds)
        assert resolved == []
        assert check.handed == []

    def test_a_deactivated_principal_is_refused_though_a_grant_covers_it(self) -> None:
        """Grant or no grant, as dispatch: a grant says the check ran, not that anyone may act."""
        principal = Deactivated()
        spec = _spec([SeedPerQuestion()])
        pool_seeds, resolved = recorded_seeds()
        with pytest.raises(PrincipalUnavailable):
            authorize(spec, principal, grant=Grant(spec, principal), pool_seeds=pool_seeds)
        assert resolved == []

    def test_a_deactivated_principal_without_pool_seeds_is_asked_as_before(self) -> None:
        """The guard is on ``pool_seeds``: django-spec-html calls ``authorize(spec, principal)``
        and a call without the keyword is no different from 0.16.0, a deactivated
        principal included (this test fails without the ``pool_seeds is not None`` conjunct)."""
        principal = Deactivated()
        spec = _spec([Unrestricted()])
        assert authorize(spec, principal).covers(spec, principal)
        assert authorize(spec, principal, seeds={"club": "chosen"}).covers(spec, principal)

    def test_a_positional_parameter_named_like_a_seed_is_not_one(self) -> None:
        """``CLASS_LEVEL`` counts two: ``club`` here is the spec, not a seed to resolve."""
        check = PositionalOnly()
        spec = _spec([check])
        pool_seeds, resolved = recorded_seeds()
        authorize(spec, "ada", pool_seeds=pool_seeds)
        assert resolved == []
        assert check.handed == [("has_permission", kernel_spec(spec))]


class TestTheCallSRequestAndView:
    """A check declaring ``request`` or ``view`` is handed what the call's context holds."""

    def test_a_check_is_handed_the_context_s_request_and_none_for_an_absent_view(self) -> None:
        check, request = SeesTheCall(), object()
        spec = SelectorSpec(kind=SelectorKind.LIST, selector=list, permissions=[check])
        authorize(spec, object(), call_context={"request": request})
        assert check.seen == [("has_permission", request, None)]

    def test_with_no_call_context_both_are_none(self) -> None:
        check = SeesTheCall()
        authorize(
            SelectorSpec(kind=SelectorKind.LIST, selector=list, permissions=[check]), object()
        )
        assert check.seen == [("has_permission", None, None)]

    def test_a_seed_resolved_for_a_check_reads_the_context_s_request(self) -> None:
        seen: list[Any] = []

        class Tenant(Unrestricted):
            def has_permission(self, principal: Any, spec: Any, *, tenant: Any) -> bool:
                seen.append(tenant)
                return True

        spec = SelectorSpec(kind=SelectorKind.LIST, selector=list, permissions=[Tenant()])
        authorize(
            spec,
            object(),
            pool_seeds=DEFAULT_POOL_SEEDS.extend(tenant=lambda *, request: request["tenant"]),
            call_context={"request": {"tenant": "acme"}},
        )
        assert seen == ["acme"]

    def test_a_seed_registered_under_the_name_outranks_the_context_s_value(self) -> None:
        """A mount registering ``request`` keeps its own, at the check as in every pool."""
        check = SeesTheCall()
        spec = SelectorSpec(kind=SelectorKind.LIST, selector=list, permissions=[check])
        authorize(
            spec,
            object(),
            pool_seeds=DEFAULT_POOL_SEEDS.extend(request=lambda: "registered"),
            call_context={"request": "context"},
        )
        assert check.seen == [("has_permission", "registered", None)]
