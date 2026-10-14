"""``aunmet_operation_affordance``: the async twin, asked in one executor hop or none."""

from __future__ import annotations

import importlib
import inspect
from typing import Any

import pytest
from asgiref.sync import sync_to_async
from django.db.models import Q

from django_service_specs.affordances.aunmet_operation_affordance import (
    aunmet_operation_affordance,
)
from django_service_specs.affordances.unmet_operation_affordance import (
    unmet_operation_affordance,
)
from django_service_specs.pool.base_pool import base_pool
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance
from django_service_specs.types.selector_kind import SelectorKind
from tests.dispatch.utils import OPEN as OPEN_PERMISSIONS
from tests.dispatch.utils import make_user, notes_of
from tests.dispatch_app.models import Note
from tests.specs.utils import Foreign

# The submodule rather than the function the package re-exports under the same
# name: the hop is looked up in this module's namespace, so it is counted there.
aunmet_module = importlib.import_module(
    "django_service_specs.affordances.aunmet_operation_affordance"
)

ROW = Affordance(code="archived", reason="Archived.", when=Q(archived=False))
OPEN = Affordance(code="open", reason="Closed.", when=lambda: True)
BOOKS_CLOSED = Affordance(code="books_closed", reason="The books are closed.", when=lambda: False)
FROZEN = Affordance(code="account_frozen", reason="The account is frozen.", when=lambda: False)


def _pool() -> dict[str, Any]:
    return base_pool(user=None)


@pytest.fixture
def hops(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The name of every function this module sends to the executor."""
    sent: list[str] = []

    def counting(fn: Any, *, thread_sensitive: bool) -> Any:
        sent.append(fn.__name__)
        return sync_to_async(fn, thread_sensitive=thread_sensitive)

    monkeypatch.setattr(aunmet_module, "sync_to_async", counting)
    return sent


def test_the_signature_is_the_sync_one() -> None:
    sync = inspect.signature(unmet_operation_affordance)
    awaited = inspect.signature(aunmet_operation_affordance)

    assert awaited.parameters == sync.parameters
    assert awaited.return_annotation == sync.return_annotation
    assert inspect.iscoroutinefunction(aunmet_operation_affordance)


@pytest.mark.parametrize(
    "affordances",
    [None, [ROW], [OPEN], [BOOKS_CLOSED], [ROW, OPEN, FROZEN, BOOKS_CLOSED]],
    ids=["undeclared", "row-only", "met", "unmet", "mixed"],
)
async def test_the_awaited_answer_is_the_sync_answer(affordances: list[Affordance] | None) -> None:
    spec = ServiceSpec(service=print, affordances=affordances)

    assert await aunmet_operation_affordance(spec, _pool()) is unmet_operation_affordance(
        spec, _pool()
    )


async def test_the_first_unmet_condition_is_the_answer() -> None:
    spec = ServiceSpec(service=print, affordances=[ROW, OPEN, FROZEN, BOOKS_CLOSED])

    assert await aunmet_operation_affordance(spec, _pool()) is FROZEN


@pytest.mark.parametrize(
    "spec",
    [
        ServiceSpec(service=print),
        ServiceSpec(service=print, affordances=[]),
        ServiceSpec(service=print, affordances=[ROW]),
        SelectorSpec(
            kind=SelectorKind.LIST,
            selector=notes_of,
            permissions=OPEN_PERMISSIONS,
            affordances={"rename": ServiceSpec(service=print, affordances=[BOOKS_CLOSED])},
        ),
    ],
    ids=["undeclared", "empty", "row-conditions-only", "selector"],
)
async def test_nothing_to_ask_at_list_time_costs_no_executor_hop(
    spec: Any, hops: list[str]
) -> None:
    assert await aunmet_operation_affordance(spec, _pool()) is None
    assert hops == []


async def test_every_condition_to_ask_is_asked_in_one_hop(hops: list[str]) -> None:
    spec = ServiceSpec(service=print, affordances=[ROW, OPEN, BOOKS_CLOSED, FROZEN])

    assert await aunmet_operation_affordance(spec, _pool()) is BOOKS_CLOSED
    assert hops == ["unmet_operation_affordance"]


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

    assert await aunmet_operation_affordance(spec, _pool()) is None
    await Note.objects.acreate(owner=ada, title="Old", archived=True)
    answer = await aunmet_operation_affordance(spec, _pool())
    assert answer is not None
    assert answer.code == "archive_pending"


async def test_a_source_answers_as_the_spec_it_compiles_to() -> None:
    source = Foreign(ServiceSpec(service=print, affordances=[OPEN, BOOKS_CLOSED]))

    assert await aunmet_operation_affordance(source, _pool()) is BOOKS_CLOSED
