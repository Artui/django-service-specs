from __future__ import annotations

import functools
import re
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec

OPEN = (Unrestricted(),)


async def _guard() -> None:
    # Awaited, this would refuse. Called sync, as dispatch calls a precondition,
    # it returns a coroutine nobody awaits, which raises nothing: the call passes.
    raise PermissionError("never reached")


async def _provide() -> dict[str, Any]:
    return {}


class _AsyncCall:
    """A callable object whose ``__call__`` is ``async def``, which ``callable()`` passes."""

    async def __call__(self) -> dict[str, Any]:
        return {}


def _service() -> None: ...


def _selector() -> list[Any]:
    return []


@pytest.mark.parametrize(
    ("field", "value", "named"),
    [
        ("preconditions", [_guard], r"ServiceSpec.preconditions\[0\] is _guard"),
        ("kwargs", _provide, r"ServiceSpec.kwargs is _provide"),
        ("input_data", _provide, r"ServiceSpec.input_data is _provide"),
        ("progress_reporter", _provide, r"ServiceSpec.progress_reporter is _provide"),
        ("kwargs", _AsyncCall(), r"ServiceSpec.kwargs is _AsyncCall"),
        ("kwargs", functools.partial(_provide), r"ServiceSpec.kwargs is partial"),
    ],
)
def test_a_service_spec_refuses_an_async_provider_or_precondition(
    field: str, value: Any, named: str
) -> None:
    with pytest.raises(ImproperlyConfigured, match=named + r", an async callable") as caught:
        ServiceSpec(service=_service, permissions=OPEN, **{field: value})
    assert "is called from sync code" in str(caught.value)


@pytest.mark.parametrize(
    ("field", "value", "named"),
    [
        ("preconditions", [_guard], r"SelectorSpec.preconditions\[0\] is _guard"),
        ("kwargs", _provide, r"SelectorSpec.kwargs is _provide"),
        ("progress_reporter", _provide, r"SelectorSpec.progress_reporter is _provide"),
    ],
)
def test_a_selector_spec_refuses_an_async_provider_or_precondition(
    field: str, value: Any, named: str
) -> None:
    with pytest.raises(ImproperlyConfigured, match=named + r", an async callable"):
        SelectorSpec(kind=SelectorKind.LIST, selector=_selector, permissions=OPEN, **{field: value})


async def _aservice() -> None: ...


async def _aselector() -> list[Any]:
    return []


def test_the_run_may_still_be_async() -> None:
    # The service and a selector spec's own selector are the one seat that may
    # be ``async def``: dispatch bridges it and ``adispatch`` awaits it.
    assert ServiceSpec(service=_aservice, permissions=OPEN).service is _aservice
    spec = SelectorSpec(kind=SelectorKind.LIST, selector=_aselector, permissions=OPEN)
    assert spec.selector is _aselector


def test_a_sync_provider_and_precondition_are_accepted() -> None:
    spec = ServiceSpec(
        service=_service,
        permissions=OPEN,
        preconditions=[_service],
        kwargs=dict,
        input_data=dict,
        progress_reporter=_service,
    )
    assert spec.preconditions == (_service,)


def test_a_value_that_is_not_callable_is_refused_before_it_is_asked_whether_it_is_async() -> None:
    with pytest.raises(
        ImproperlyConfigured, match=re.escape("ServiceSpec.kwargs must be callable; got int.")
    ):
        ServiceSpec(service=_service, permissions=OPEN, kwargs=3)


async def _guard_lazily() -> Any:
    # An async generator function: ``iscoroutinefunction`` says no, and calling
    # it returns a generator object that never runs and is truthy.
    yield


def test_an_async_generator_precondition_is_refused() -> None:
    with pytest.raises(
        ImproperlyConfigured,
        match=r"ServiceSpec.preconditions\[0\] is _guard_lazily, an async callable",
    ):
        ServiceSpec(service=_service, permissions=OPEN, preconditions=[_guard_lazily])


class _AsyncClassLevel(PermissionCheck):
    async def has_permission(self, principal: Any, spec: Any) -> bool:
        return False


class _AsyncObjectLevel(PermissionCheck):
    def has_permission(self, principal: Any, spec: Any) -> bool:
        return True

    async def has_object_permission(self, principal: Any, spec: Any, target: Any) -> bool:
        return False


class _AsyncScopeLevel(PermissionCheck):
    def has_permission(self, principal: Any, spec: Any) -> bool:
        return True

    async def has_scope_permission(self, principal: Any, spec: Any, scope: Any) -> bool:
        return False


class _AsyncGeneratorClassLevel(PermissionCheck):
    async def has_permission(self, principal: Any, spec: Any) -> Any:
        yield False


class TestAnAsyncPermissionCheckIsRefused:
    """A check method is read for truth from sync code; an ``async def`` one never refuses.

    One case per method, because the methods are named in one tuple and
    coverage cannot see a name dropped from it.
    """

    @pytest.mark.parametrize(
        ("check", "method"),
        [
            (_AsyncClassLevel(), "has_permission"),
            (_AsyncObjectLevel(), "has_object_permission"),
            (_AsyncScopeLevel(), "has_scope_permission"),
            (_AsyncGeneratorClassLevel(), "has_permission"),
        ],
    )
    def test_on_a_service_spec(self, check: PermissionCheck, method: str) -> None:
        named = f"ServiceSpec.permissions[1].{method} is {type(check).__name__}.{method}"
        with pytest.raises(ImproperlyConfigured, match=re.escape(named + ", an async callable")):
            ServiceSpec(service=_service, permissions=[Unrestricted(), check])

    def test_on_a_selector_spec(self) -> None:
        named = "SelectorSpec.permissions[0].has_object_permission is _AsyncObjectLevel"
        with pytest.raises(ImproperlyConfigured, match=re.escape(named)):
            SelectorSpec(
                kind=SelectorKind.RETRIEVE, selector=_selector, permissions=[_AsyncObjectLevel()]
            )
