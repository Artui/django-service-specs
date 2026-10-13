"""Tests for non-exported helpers in selectors/utils.py."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Generator
from typing import Any

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.selectors.shape_queryset import shape_queryset
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from tests.dispatch.utils import make_user
from tests.dispatch_app.models import Note


async def _later(queryset: Any) -> Any:
    return queryset


async def _rows(queryset: Any) -> AsyncIterator[Any]:
    yield queryset


class _Pending:
    """An awaitable that is not a coroutine, as a ``Future`` or a Task is not."""

    def __await__(self) -> Generator[Any, None, Any]:
        yield
        return None


def _spec(extend: Any) -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.LIST,
        selector=lambda: Note.objects.all(),
        # A plain ``def``, which the spec accepts as sync, handing back what
        # is still to be awaited: an ``async def`` itself is refused when the
        # spec is built.
        extend_queryset=extend,
        permissions=[Unrestricted()],
    )


@pytest.mark.django_db
class TestAnExtendQuerysetAnsweringWithAnAwaitable:
    """``extend_queryset`` is called from sync code and never awaited.

    What it hands back stood in for the queryset, so dispatch returned an
    unawaited coroutine as a list's value.
    """

    def test_a_coroutine_is_refused_and_closed(self) -> None:
        handed: list[Any] = []

        def extend(queryset: Any) -> Any:
            handed.append(_later(queryset))
            return handed[0]

        with pytest.raises(ImproperlyConfigured, match=r"extend_queryset .* \(coroutine\)"):
            shape_queryset(Permission.objects.all(), _spec(extend), {}, source_label="x")
        # Closed, so it does not linger to warn that it was never awaited.
        assert inspect.getcoroutinestate(handed[0]) == inspect.CORO_CLOSED

    def test_dispatch_refuses_it_rather_than_returning_it(self) -> None:
        with pytest.raises(ImproperlyConfigured, match="extend_queryset"):
            dispatch(
                _spec(lambda queryset: _later(queryset)),
                principal=make_user("ada"),
                arguments={},
            )

    def test_an_awaitable_that_is_not_a_coroutine_is_refused(self) -> None:
        with pytest.raises(ImproperlyConfigured, match=r"extend_queryset .* \(_Pending\)"):
            shape_queryset(
                Permission.objects.all(),
                _spec(lambda queryset: _Pending()),
                {},
                source_label="x",
            )

    def test_an_async_generator_is_refused(self) -> None:
        with pytest.raises(ImproperlyConfigured, match=r"extend_queryset .* \(async_generator\)"):
            shape_queryset(
                Permission.objects.all(),
                _spec(lambda queryset: _rows(queryset)),
                {},
                source_label="x",
            )
