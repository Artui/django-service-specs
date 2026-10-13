from __future__ import annotations

import inspect
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.authorize import authorize
from django_service_specs.authorization.grant import Grant
from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.dispatch.adispatch import adispatch
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from tests.authorization.utils import (
    Allow,
    AnswersWith,
    NotACoroutine,
    Refuse,
    RefuseWithMessage,
    refuses,
    refuses_lazily,
)


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
