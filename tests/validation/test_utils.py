"""``validator_parameters``: how the kernel asks a Validator what it takes, inside a call or outside one."""

from __future__ import annotations

import functools
import gc
import weakref
from collections.abc import Callable, Mapping
from typing import Any, cast
from unittest import mock

import pytest

from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.validation import utils
from django_service_specs.validation.utils import validator_parameters
from django_service_specs.validation.validation_context import ValidationContext
from django_service_specs.validation.validator import Validator

TITLE = Parameters.of(Parameter("title", "string"))

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


def test_the_signature_is_read_once_per_function(monkeypatch: pytest.MonkeyPatch) -> None:
    """Read once for the function the class defines, across asks and instances:
    a cache under the bound method, made afresh on each lookup, reads it on
    every ask."""
    read: list[Any] = []
    names = utils._names_call_context

    def counted(asked: Callable[..., Any]) -> bool:
        read.append(asked)
        return names(asked)

    class Counted(_KeywordOnly):
        def parameters(self, *, call_context: dict[str, Any] | None = NOT_HANDED) -> Parameters:
            return super().parameters(call_context=call_context)

    monkeypatch.setattr(utils, "_names_call_context", counted)
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
