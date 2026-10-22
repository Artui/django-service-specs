"""The shared phases, where a property is sharper stated on the phase than through dispatch."""

from __future__ import annotations

import inspect
from collections.abc import Generator
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist
from django.http import Http404

from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.utils import (
    NOT_FOUND,
    call_pool,
    reraise_unless_retrieve,
    run_preconditions,
    validate_arguments,
)
from django_service_specs.pool.null_progress import null_progress
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
from tests.dispatch.utils import OPEN, PK, Record, Titled

PRINCIPAL = object()
ROW = object()


def test_not_found_is_the_empty_not_found_result() -> None:
    assert DispatchResult(kind="not_found") == NOT_FOUND


def test_the_validator_sees_only_the_arguments_it_declares() -> None:
    validator = Titled()
    spec = ServiceSpec(
        service=Record(),
        permissions=OPEN,
        validator=validator,
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE, selector=Record(), reads=PK
        ),
    )

    validated = validate_arguments(
        spec,
        {"pk": 1, "title": " t "},
        principal=PRINCIPAL,
        target=ROW,
        server_input={},
        call_context={},
    )

    assert validated.values == validated.data == {"title": "t"}
    ((arguments, context),) = validator.calls
    assert arguments == {"title": " t "}
    assert context.principal is PRINCIPAL
    assert context.target is ROW


def test_a_spec_with_no_validator_validates_to_nothing() -> None:
    spec = ServiceSpec(service=Record(), permissions=OPEN)

    validated = validate_arguments(
        spec, {"pk": 1}, principal=PRINCIPAL, target=ROW, server_input={}, call_context={}
    )
    assert validated.values == validated.data == {}


@pytest.mark.parametrize("error", [ObjectDoesNotExist("gone"), Http404("gone")])
@pytest.mark.parametrize("kind", [SelectorKind.RETRIEVE, SelectorKind.LIST])
def test_does_not_exist_and_http404_are_a_missing_row_only_for_a_retrieve(
    kind: SelectorKind, error: Exception
) -> None:
    spec = SelectorSpec(kind=kind, selector=Record())

    if kind is SelectorKind.RETRIEVE:
        assert reraise_unless_retrieve(spec, error) is None
        return
    with pytest.raises(type(error)) as caught:
        reraise_unless_retrieve(spec, error)
    assert caught.value is error


def test_seeds_resolve_before_the_call_s_own_entries_exist() -> None:
    seeds = DEFAULT_POOL_SEEDS.extend(seen=lambda **pool: sorted(pool))

    pool: dict[str, Any] = call_pool(PRINCIPAL, seeds, {"pk": 1, "data": {}}, early={})

    assert pool == {
        "user": PRINCIPAL,
        "progress": null_progress,
        "seen": ["progress", "user"],
        "pk": 1,
        "data": {},
    }


class _NotACoroutine:
    """Awaitable without being a coroutine, as a ``Future`` or a task is."""

    def __await__(self) -> Generator[None, None, None]:
        yield


async def _refuse() -> None:
    raise RuntimeError("closed")


async def _refuse_lazily() -> Any:
    raise RuntimeError("closed")
    yield


class TestAPreconditionAnsweringWithAnAwaitable:
    """A precondition's answer is ignored, unless it is one still to be awaited: refused, never a pass.

    Each precondition is a plain callable returning the object, a shape no
    declaration can refuse. Each shape holds one condition of ``sync_result``.
    """

    @staticmethod
    def _spec(answer: Any) -> ServiceSpec:
        def precondition() -> Any:
            return answer

        return ServiceSpec(service=Record(), permissions=OPEN, preconditions=[precondition])

    def test_a_coroutine_is_refused_and_closed(self) -> None:
        answer = _refuse()
        with pytest.raises(ImproperlyConfigured, match="answered with an awaitable") as caught:
            run_preconditions(self._spec(answer), {}, fillable=frozenset())
        assert "precondition" in str(caught.value)
        assert inspect.getcoroutinestate(answer) == inspect.CORO_CLOSED

    def test_an_awaitable_that_is_not_a_coroutine_is_refused(self) -> None:
        with pytest.raises(ImproperlyConfigured, match="answered with an awaitable"):
            run_preconditions(self._spec(_NotACoroutine()), {}, fillable=frozenset())

    def test_an_async_generator_is_refused(self) -> None:
        # Not awaitable, so ``isawaitable`` alone would read it as a pass.
        with pytest.raises(ImproperlyConfigured, match="answered with an awaitable"):
            run_preconditions(self._spec(_refuse_lazily()), {}, fillable=frozenset())

    def test_any_other_answer_is_ignored(self) -> None:
        run_preconditions(self._spec(False), {}, fillable=frozenset())
