"""``aenforce_affordances``: the async twin, answering every condition in one executor hop."""

from __future__ import annotations

import importlib
import inspect
from typing import Any

import pytest
from asgiref.sync import sync_to_async
from django.db.models import Q

from django_service_specs.affordances.aenforce_affordances import aenforce_affordances
from django_service_specs.affordances.enforce_affordances import enforce_affordances
from django_service_specs.pool.base_pool import base_pool
from django_service_specs.services.action_unavailable import ActionUnavailable
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance
from django_service_specs.types.selector_kind import SelectorKind
from tests.affordances.utils import count_hops
from tests.dispatch.utils import make_user
from tests.dispatch_app.models import Note
from tests.specs.utils import Foreign

aenforce_module = importlib.import_module("django_service_specs.affordances.aenforce_affordances")

NOT_ARCHIVED = Affordance(
    code="note_archived", reason="An archived note cannot be renamed.", when=Q(archived=False)
)
OPEN = Affordance(code="open", reason="Closed.", when=lambda: True)
BOOKS_CLOSED = Affordance(code="books_closed", reason="The books are closed.", when=lambda: False)


def _pool() -> dict[str, Any]:
    return base_pool(user=None)


@pytest.fixture
def hops(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    return count_hops(monkeypatch, aenforce_module)


def test_the_signature_is_the_sync_one() -> None:
    sync, awaited = inspect.signature(enforce_affordances), inspect.signature(aenforce_affordances)

    assert awaited.parameters == sync.parameters
    assert inspect.iscoroutinefunction(aenforce_affordances)


async def test_an_unmet_condition_refuses_with_its_code_and_reason() -> None:
    spec = ServiceSpec(service=print, affordances=[OPEN, BOOKS_CLOSED])

    with pytest.raises(ActionUnavailable) as caught:
        await aenforce_affordances(spec, _pool(), instance=None)

    assert caught.value.code == "books_closed"
    assert caught.value.message == "The books are closed."


@pytest.mark.parametrize("affordances", [None, [], [OPEN]], ids=["undeclared", "empty", "met"])
async def test_a_met_or_undeclared_condition_lets_the_call_through(
    affordances: list[Affordance] | None,
) -> None:
    spec = ServiceSpec(service=print, affordances=affordances)

    assert await aenforce_affordances(spec, _pool(), instance=None) is None


@pytest.mark.parametrize("affordances", [None, []], ids=["undeclared", "empty"])
async def test_declaring_nothing_costs_no_executor_hop(
    affordances: list[Affordance] | None, hops: list[str]
) -> None:
    await aenforce_affordances(
        ServiceSpec(service=print, affordances=affordances), {}, instance=None
    )

    assert hops == []


@pytest.mark.django_db(transaction=True)
async def test_every_condition_is_answered_in_one_hop(hops: list[str]) -> None:
    ada = await sync_to_async(make_user)("ada")
    note = await Note.objects.acreate(owner=ada, title="Draft", archived=True)
    spec = ServiceSpec(service=print, affordances=[OPEN, NOT_ARCHIVED, BOOKS_CLOSED])

    with pytest.raises(ActionUnavailable) as caught:
        await aenforce_affordances(spec, _pool(), instance=note)

    assert caught.value.code == "note_archived"
    assert hops == ["enforce_affordances"]


@pytest.mark.django_db(transaction=True)
async def test_a_condition_that_queries_runs_off_the_loop() -> None:
    """On the loop the ORM raises ``SynchronousOnlyOperation`` before answering."""

    def nothing_archived() -> bool:
        return not Note.objects.filter(archived=True).exists()

    spec = ServiceSpec(
        service=print,
        affordances=[Affordance(code="archive_pending", reason="r", when=nothing_archived)],
    )
    ada = await sync_to_async(make_user)("ada")

    assert await aenforce_affordances(spec, _pool(), instance=None) is None
    await Note.objects.acreate(owner=ada, title="Old", archived=True)
    with pytest.raises(ActionUnavailable) as caught:
        await aenforce_affordances(spec, _pool(), instance=None)
    assert caught.value.code == "archive_pending"


async def test_a_source_refuses_as_the_spec_it_compiles_to() -> None:
    source = Foreign(ServiceSpec(service=print, affordances=[OPEN, BOOKS_CLOSED]))

    with pytest.raises(ActionUnavailable) as caught:
        await aenforce_affordances(source, _pool(), instance=None)

    assert caught.value.code == "books_closed"


async def test_a_source_declaring_nothing_costs_no_executor_hop(hops: list[str]) -> None:
    await aenforce_affordances(Foreign(ServiceSpec(service=print)), {}, instance=None)

    assert hops == []


@pytest.mark.parametrize("wrapped", [False, True], ids=["spec", "source"])
async def test_a_selector_spec_is_refused_as_the_sync_function_refuses_it(wrapped: bool) -> None:
    # Declaring no affordances, so a check that answered "nothing declared"
    # before asking what kind of spec it holds would let it through.
    selector = SelectorSpec(kind=SelectorKind.LIST, selector=list)
    spec: Any = Foreign(selector) if wrapped else selector
    with pytest.raises(TypeError) as sync:
        enforce_affordances(spec, _pool(), instance=None)

    with pytest.raises(TypeError) as awaited:
        await aenforce_affordances(spec, _pool(), instance=None)

    assert str(awaited.value) == str(sync.value)


# The call's context: a transport asking ahead of a call has one to hand, or
# the condition gets a dict of its own rather than a TypeError.


def _naming_it(handed: list[Any]) -> ServiceSpec:
    def when(*, call_context: Any) -> bool:
        handed.append(call_context)
        return True

    return ServiceSpec(
        service=print,
        affordances=[
            Affordance(code="first", reason="r", when=when),
            Affordance(code="second", reason="r", when=when),
        ],
    )


async def test_a_condition_naming_the_call_context_is_handed_the_dict_passed() -> None:
    handed: list[Any] = []
    context: dict[str, Any] = {}
    await aenforce_affordances(
        _naming_it(handed), base_pool(user=None), instance=None, call_context=context
    )
    assert len(handed) == 2
    assert all(seen is context for seen in handed)


async def test_with_none_passed_its_conditions_share_a_fresh_dict() -> None:
    handed: list[Any] = []
    spec = _naming_it(handed)
    await aenforce_affordances(spec, base_pool(user=None), instance=None)
    await aenforce_affordances(spec, base_pool(user=None), instance=None)
    first, again, second, _ = handed
    assert first == {}
    assert again is first
    assert second is not first


async def test_a_catch_all_condition_is_handed_the_seeds_and_never_the_call_context() -> None:
    seen: list[set[str]] = []

    def when(**kwargs: Any) -> bool:
        seen.append(set(kwargs))
        return True

    spec = ServiceSpec(service=print, affordances=[Affordance(code="a", reason="r", when=when)])
    await aenforce_affordances(spec, base_pool(user=None), instance=None, call_context={})
    assert seen == [{"user", "progress"}]
