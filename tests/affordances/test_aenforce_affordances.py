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
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance
from tests.dispatch.utils import make_user
from tests.dispatch_app.models import Note

# The submodule rather than the function the package re-exports under the same
# name: the hop is looked up in this module's namespace, so it is counted there.
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
    """The name of every function this module sends to the executor."""
    sent: list[str] = []

    def counting(fn: Any, *, thread_sensitive: bool) -> Any:
        sent.append(fn.__name__)
        return sync_to_async(fn, thread_sensitive=thread_sensitive)

    monkeypatch.setattr(aenforce_module, "sync_to_async", counting)
    return sent


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
