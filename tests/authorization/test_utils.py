"""``asked_with``, which the three ``authorize`` functions share: what a check is handed."""

from __future__ import annotations

import functools
import gc
import types
import weakref
from dataclasses import dataclass
from typing import Any, cast

import pytest

from django_service_specs.authorization import utils
from django_service_specs.authorization.utils import asked_with


class _Shapes:
    """One method per way a parameter named ``arguments`` can be declared, or not."""

    def keyword_only(self, principal: Any, spec: Any, *, arguments: Any = None) -> bool:
        return True

    def positional_or_keyword(self, principal: Any, spec: Any, arguments: Any = None) -> bool:
        return True

    def positional_only(self, principal: Any, spec: Any, arguments: Any = None, /) -> bool:
        return True

    def variadic(self, principal: Any, spec: Any, *arguments: Any) -> bool:
        return True

    def spread_under_the_name(self, principal: Any, spec: Any, **arguments: Any) -> bool:
        return True

    def spread(self, principal: Any, spec: Any, **kwargs: Any) -> bool:
        return True

    def undeclared(self, principal: Any, spec: Any) -> bool:
        return True


@pytest.mark.parametrize("method", ["keyword_only", "positional_or_keyword"])
def test_a_parameter_a_keyword_reaches_is_handed_the_arguments(method: str) -> None:
    handed = {"pk": 1}
    assert asked_with(_Shapes(), method, handed) == {"arguments": handed}


@pytest.mark.parametrize("method", ["spread", "undeclared"])
def test_a_method_that_names_no_arguments_is_handed_nothing(method: str) -> None:
    assert asked_with(_Shapes(), method, {"pk": 1}) == {}


@pytest.mark.parametrize("method", ["positional_only", "variadic", "spread_under_the_name"])
def test_a_parameter_named_arguments_that_no_keyword_reaches_is_handed_nothing(
    method: str,
) -> None:
    assert asked_with(_Shapes(), method, {"pk": 1}) == {}


def test_a_check_is_not_kept_once_asked() -> None:
    """The signature is cached under the function a bound method wraps, never
    under the bound method, which would hold its check for the process's life."""
    check = _Shapes()
    held = weakref.ref(check)
    assert asked_with(check, "keyword_only", {"pk": 1}) == {"arguments": {"pk": 1}}
    del check
    gc.collect()
    assert held() is None


def test_a_callable_set_on_the_instance_is_not_kept_once_asked() -> None:
    """Only a function a class defines is cached; one set on an instance, or
    a mock, is read uncached, so a cache does not hold every one ever asked."""
    check = _Shapes()

    def shadow(principal: Any, spec: Any, *, arguments: Any = None) -> bool:
        return True

    cast(Any, check).undeclared = shadow
    held = weakref.ref(shadow)
    assert asked_with(check, "undeclared", {"pk": 1}) == {"arguments": {"pk": 1}}
    del check, shadow
    gc.collect()
    assert held() is None


def _forwarding(method: Any) -> Any:
    @functools.wraps(method)
    def forwarded(*args: Any, **kwargs: Any) -> Any:
        return method(*args, **kwargs)

    return forwarded


def test_a_forwarding_wrapper_answers_for_the_method_it_wraps() -> None:
    class Wrapped(_Shapes):
        keyword_only = _forwarding(_Shapes.keyword_only)
        undeclared = _forwarding(_Shapes.undeclared)

    assert asked_with(Wrapped(), "keyword_only", {"pk": 1}) == {"arguments": {"pk": 1}}
    assert asked_with(Wrapped(), "undeclared", {"pk": 1}) == {}


def test_a_class_defined_function_s_signature_is_inspected_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A call asks each check up to twice, and many checks share a class, so
    the signature is read once per function rather than once per question."""
    read: list[Any] = []

    def counted(asked: Any) -> bool:
        read.append(asked)
        return True

    class Asking(_Shapes):
        def keyword_only(self, principal: Any, spec: Any, *, arguments: Any = None) -> bool:
            return True

    monkeypatch.setattr(utils, "_names_arguments", counted)
    for check in (Asking(), Asking()):
        asked_with(check, "keyword_only", {"pk": 1})
    assert read == [Asking.keyword_only]


def test_a_class_built_at_runtime_is_not_kept_once_asked() -> None:
    """A check class a factory builds per call is freed with its last
    instance, so the cache does not grow with every class ever asked."""

    def build() -> Any:
        class Built(_Shapes):
            def keyword_only(self, principal: Any, spec: Any, *, arguments: Any = None) -> bool:
                return True

        return Built()

    check = build()
    held = weakref.ref(type(check).keyword_only)
    assert asked_with(check, "keyword_only", {"pk": 1}) == {"arguments": {"pk": 1}}
    del check
    gc.collect()
    assert held() is None


def test_a_wrapped_chain_that_loops_is_handed_nothing() -> None:
    def forwarded(*args: Any, **kwargs: Any) -> bool:
        return True

    cast(Any, forwarded).__wrapped__ = forwarded
    check = _Shapes()
    cast(Any, check).undeclared = forwarded
    assert asked_with(check, "undeclared", {"pk": 1}) == {}


def test_a_decorator_without_wraps_answers_for_its_own_spread_alone() -> None:
    """With no ``__wrapped__`` there is nothing to walk to: ``**kwargs`` over
    nothing named is not handed the keyword."""

    def unwrapped(*args: Any, **kwargs: Any) -> bool:
        return _Shapes.keyword_only(*args, **kwargs)

    check = _Shapes()
    cast(Any, check).keyword_only = unwrapped
    assert asked_with(check, "keyword_only", {"pk": 1}) == {}


def test_a_forwarding_wrapper_over_a_positional_only_arguments_is_handed_nothing() -> None:
    check = _Shapes()
    cast(Any, check).positional_only = _forwarding(_Shapes.positional_only)
    assert asked_with(check, "positional_only", {"pk": 1}) == {}


def test_a_callable_with_no_signature_is_handed_nothing() -> None:
    """``inspect.signature`` raises ``ValueError`` for a builtin method; it
    never opted in, so it is read as not having done so."""
    check = _Shapes()
    cast(Any, check).undeclared = "abc".startswith
    assert asked_with(check, "undeclared", {"pk": 1}) == {}


def test_a_wrapped_layer_that_is_not_callable_is_handed_nothing() -> None:
    """``inspect.signature`` raises ``TypeError`` for a ``__wrapped__`` that
    cannot be called; the walk stops there, not opted in."""

    def forwarded(*args: Any, **kwargs: Any) -> bool:
        return True

    cast(Any, forwarded).__wrapped__ = 5
    check = _Shapes()
    cast(Any, check).undeclared = forwarded
    assert asked_with(check, "undeclared", {"pk": 1}) == {}


@dataclass
class _UnhashableRule:
    """A callable object with ``eq`` and so no hash."""

    def __call__(self, principal: Any, spec: Any) -> bool:
        return True


def test_a_method_binding_a_callable_object_is_read_uncached() -> None:
    """``MethodType`` binds any callable, and its ``__func__`` here has no
    hash: only a plain function is a cache key, so it is read uncached."""
    check = _Shapes()
    cast(Any, check).undeclared = types.MethodType(_UnhashableRule(), check)
    assert asked_with(check, "undeclared", {"pk": 1}) == {}
