"""``sync_answer``: the one reading of a permission check's answer, for whoever asks a check."""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

import django_service_specs
from django_service_specs.authorization.sync_answer import sync_answer
from tests.authorization.utils import NotACoroutine, refuses, refuses_lazily


def test_it_is_the_root_s_own_function() -> None:
    assert django_service_specs.sync_answer is sync_answer


@pytest.mark.parametrize("answer", [True, False, None, 0, "", object()])
def test_an_answer_that_is_not_awaitable_comes_back_as_it_is(answer: Any) -> None:
    # Truth is the caller's to read: this refuses what could never be read as an answer.
    assert sync_answer(answer, asked="Check.has_permission") is answer


def test_a_coroutine_is_refused_naming_the_method_and_closed() -> None:
    answer = refuses()
    with pytest.raises(ImproperlyConfigured, match="answered with an awaitable") as caught:
        sync_answer(answer, asked="Prompted.has_permission")
    assert "Prompted.has_permission answered with an awaitable (coroutine)" in str(caught.value)
    assert inspect.getcoroutinestate(answer) == inspect.CORO_CLOSED


def test_an_awaitable_that_is_not_a_coroutine_is_refused() -> None:
    # Without the ``isawaitable`` disjunct this is truthy and passes; the
    # ``iscoroutine`` guard is what keeps ``close()`` off it.
    with pytest.raises(ImproperlyConfigured, match="answered with an awaitable"):
        sync_answer(NotACoroutine(), asked="Check.has_permission")


def test_an_async_generator_is_refused() -> None:
    # Not awaitable, so ``isawaitable`` alone would let it through as true.
    with pytest.raises(ImproperlyConfigured, match="answered with an awaitable"):
        sync_answer(refuses_lazily(), asked="Check.has_permission")
