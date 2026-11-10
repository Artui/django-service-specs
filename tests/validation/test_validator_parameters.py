"""``validator_parameters``: how a Validator is asked what it takes, in a call or outside one."""

from __future__ import annotations

import functools
import gc
import importlib
import types
import weakref
from collections.abc import Callable, Mapping
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

import pytest

import django_service_specs
import django_service_specs.validation
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator
from django_service_specs.validation.validator_parameters import validator_parameters

TITLE = Parameters.of(Parameter("title", "string"))

# By import path, because the package re-exports the function under the
# module's own name, and attribute access on the package finds the function.
_module = importlib.import_module("django_service_specs.validation.validator_parameters")

# What a recording ``parameters`` defaults its keyword to, so a test tells a
# keyword left out from one passed as ``None``.
NOT_HANDED: Any = object()


class _Recording(Validator):
    """Validates nothing; each subclass declares ``parameters`` one way and records what it got."""

    def __init__(self) -> None:
        self.handed: list[Any] = []

    def parameters(self) -> Parameters:
        self.handed.append(NOT_HANDED)
        return TITLE

    def validate(self, arguments: Mapping[str, Any], context: ValidationContext) -> dict[str, Any]:
        return {}


class _KeywordOnly(_Recording):
    def parameters(self, *, call_context: dict[str, Any] | None = NOT_HANDED) -> Parameters:
        self.handed.append(call_context)
        return TITLE


class _PositionalOrKeyword(_Recording):
    def parameters(self, call_context: dict[str, Any] | None = NOT_HANDED) -> Parameters:
        self.handed.append(call_context)
        return TITLE


class _PositionalOnly(_Recording):
    def parameters(self, call_context: dict[str, Any] | None = NOT_HANDED, /) -> Parameters:
        self.handed.append(call_context)
        return TITLE


class _KwargsOnly(_Recording):
    def parameters(self, **kwargs: Any) -> Parameters:
        self.handed.append(kwargs)
        return TITLE


@pytest.mark.parametrize("validator_class", [_KeywordOnly, _PositionalOrKeyword])
def test_a_validator_declaring_call_context_is_handed_the_call_s_dict(
    validator_class: type[_Recording],
) -> None:
    validator = validator_class()
    context: dict[str, Any] = {}
    assert validator_parameters(validator, call_context=context) is TITLE
    assert len(validator.handed) == 1
    assert validator.handed[0] is context


def test_an_opted_in_validator_asked_outside_a_call_is_handed_no_keyword() -> None:
    validator = _KeywordOnly()
    assert validator_parameters(validator, call_context=None) is TITLE
    assert validator.handed == [NOT_HANDED]


def test_a_validator_declaring_no_call_context_is_asked_as_before() -> None:
    validator = _Recording()
    assert validator_parameters(validator, call_context={}) is TITLE
    assert validator.handed == [NOT_HANDED]


def test_a_positional_only_call_context_is_handed_nothing() -> None:
    """No keyword reaches it, so passing one would raise."""
    validator = _PositionalOnly()
    assert validator_parameters(validator, call_context={}) is TITLE
    assert validator.handed == [NOT_HANDED]


def test_a_kwargs_only_parameters_is_handed_nothing() -> None:
    validator = _KwargsOnly()
    assert validator_parameters(validator, call_context={}) is TITLE
    assert validator.handed == [{}]


def test_a_mock_parameters_is_handed_nothing() -> None:
    validator = _Recording()
    asked = mock.Mock(return_value=TITLE)
    cast(Any, validator).parameters = asked
    assert validator_parameters(validator, call_context={}) is TITLE
    asked.assert_called_once_with()


def _forwarding(method: Callable[..., Parameters]) -> Callable[..., Parameters]:
    """A ``functools.wraps`` decorator that names nothing itself and forwards what it is handed."""

    @functools.wraps(method)
    def forwarded(self: Any, *args: Any, **kwargs: Any) -> Parameters:
        return method(self, *args, **kwargs)

    return forwarded


def test_a_wrapper_not_naming_the_keyword_is_handed_nothing() -> None:
    """The method's own signature decides, never the ``__wrapped__`` chain:
    the function beneath names the keyword, the wrapper called does not."""

    class Wrapped(_KeywordOnly):
        parameters = _forwarding(_KeywordOnly.parameters)

    validator = Wrapped()
    assert validator_parameters(validator, call_context={}) is TITLE
    assert validator.handed == [NOT_HANDED]


def test_a_wrapper_naming_the_keyword_itself_is_handed_it() -> None:
    def naming(method: Callable[..., Parameters]) -> Callable[..., Parameters]:
        @functools.wraps(method)
        def forwarded(self: Any, *, call_context: Any = NOT_HANDED) -> Parameters:
            return method(self, call_context=call_context)

        return forwarded

    class Wrapped(_KeywordOnly):
        parameters = naming(_KeywordOnly.parameters)

    validator = Wrapped()
    context: dict[str, Any] = {}
    validator_parameters(validator, call_context=context)
    assert validator.handed[0] is context


def test_a_parameters_with_no_signature_is_asked_as_before() -> None:
    """``inspect.signature`` raises for a ``__signature__`` that is not one;
    such a callable never declared the keyword."""

    def unreadable() -> Parameters:
        return TITLE

    cast(Any, unreadable).__signature__ = "not a signature"
    validator = _Recording()
    cast(Any, validator).parameters = unreadable
    assert validator_parameters(validator, call_context={}) is TITLE


def test_a_parameters_whose_signature_read_raises_value_error_is_asked_as_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``inspect.signature`` raises ``ValueError`` for a builtin with no signature
    to read; which builtins vary by Python version, so the read is made to raise it.
    A class built here, so no earlier ask has cached its answer."""

    def unreadable(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("no signature found")

    class Fresh(_KeywordOnly):
        def parameters(self, *, call_context: dict[str, Any] | None = NOT_HANDED) -> Parameters:
            return super().parameters(call_context=call_context)

    monkeypatch.setattr(_module, "inspect", SimpleNamespace(signature=unreadable))
    validator = Fresh()
    assert validator_parameters(validator, call_context={}) is TITLE
    assert validator.handed == [NOT_HANDED]


def test_a_method_binding_an_unhashable_callable_is_handed_the_call_s_dict() -> None:
    """``MethodType`` binds any callable, so ``__func__`` is not always a function
    and not always hashable: it is read uncached, never used as a cache key."""

    class Unhashable:
        # Defining ``__eq__`` without ``__hash__`` leaves it unhashable.
        def __init__(self) -> None:
            self.handed: list[Any] = []

        def __eq__(self, other: object) -> bool:
            return self is other

        def __call__(self, owner: Any, *, call_context: dict[str, Any] | None = None) -> Parameters:
            self.handed.append(call_context)
            return TITLE

    bound = Unhashable()
    validator = _Recording()
    cast(Any, validator).parameters = types.MethodType(bound, validator)
    context: dict[str, Any] = {}
    assert validator_parameters(validator, call_context=context) is TITLE
    assert len(bound.handed) == 1
    assert bound.handed[0] is context


def test_the_signature_is_read_once_per_function(monkeypatch: pytest.MonkeyPatch) -> None:
    """Read once for the function the class defines, across asks and instances:
    a cache under the bound method, made afresh on each lookup, reads it on
    every ask."""
    read: list[Any] = []
    names = _module._names_call_context

    def counted(asked: Callable[..., Any]) -> bool:
        read.append(asked)
        return names(asked)

    class Counted(_KeywordOnly):
        def parameters(self, *, call_context: dict[str, Any] | None = NOT_HANDED) -> Parameters:
            return super().parameters(call_context=call_context)

    monkeypatch.setattr(_module, "_names_call_context", counted)
    context: dict[str, Any] = {}
    validators = (Counted(), Counted())
    for validator in (*validators, *validators):
        validator_parameters(validator, call_context=context)
    assert len(read) == 1
    assert all(validator.handed == [context, context] for validator in validators)


def test_a_validator_class_built_at_runtime_is_not_kept_once_asked() -> None:
    def build() -> _Recording:
        class Built(_KeywordOnly):
            def parameters(self, *, call_context: dict[str, Any] | None = None) -> Parameters:
                return TITLE

        return Built()

    validator = build()
    held = weakref.ref(cast(Any, type(validator).parameters))
    validator_parameters(validator, call_context={})
    del validator
    gc.collect()
    assert held() is None


class TestThePublicName:
    """A transport describing a Validator per call asks it as dispatch does, through the
    public name, so a third-party Validator that opts in is handed the call's dict too."""

    @pytest.mark.parametrize("package", [django_service_specs.validation, django_service_specs])
    def test_it_is_exported(self, package: Any) -> None:
        assert "validator_parameters" in package.__all__
        assert getattr(package, "validator_parameters", None) is validator_parameters

    @pytest.mark.parametrize("package", [django_service_specs.validation, django_service_specs])
    def test_an_opted_in_validator_is_handed_the_call_s_dict_through_it(self, package: Any) -> None:
        class OptedIn(_Recording):
            def parameters(self, *, call_context: dict[str, Any] | None = None) -> Parameters:
                self.handed.append(call_context)
                return TITLE

        validator = OptedIn()
        context: dict[str, Any] = {}
        asked = getattr(package, "validator_parameters", None)
        assert asked is not None
        assert asked(validator, call_context=context) is TITLE
        assert validator.handed == [context]
        assert validator.handed[0] is context
