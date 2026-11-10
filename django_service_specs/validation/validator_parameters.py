from __future__ import annotations

import inspect
import weakref
from collections.abc import Callable
from types import FunctionType
from typing import Any, Final, cast

from django_service_specs.parameters.parameters import Parameters
from django_service_specs.validation.validator import Validator


def validator_parameters(
    validator: Validator, *, call_context: dict[str, Any] | None
) -> Parameters:
    """``validator.parameters()``, handed ``call_context`` where it declares the keyword."""
    asked = cast(Callable[..., Parameters], validator.parameters)
    if call_context is not None and _declares(asked):
        return asked(call_context=call_context)
    return asked()


def _declares(asked: Callable[..., Any]) -> bool:
    """Whether ``asked`` names ``call_context`` as a parameter a keyword reaches."""
    function = getattr(asked, "__func__", None)
    if not isinstance(function, FunctionType):
        return _names_call_context(asked)
    declares = _DECLARES.get(function)
    if declares is None:
        declares = _DECLARES[function] = _names_call_context(asked)
    return declares


# Keyed weakly on the function, so a Validator class built at runtime is freed
# with its last instance and the cache does not grow with every class asked
# (test_a_validator_class_built_at_runtime_is_not_kept_once_asked).
_DECLARES: Final[weakref.WeakKeyDictionary[FunctionType, bool]] = weakref.WeakKeyDictionary()


def _names_call_context(asked: Callable[..., Any]) -> bool:
    """``_declares``, read off ``asked``'s signature."""
    try:
        parameter = inspect.signature(asked, follow_wrapped=False).parameters.get(_KEYWORD)
    except (ValueError, TypeError):
        return False
    return parameter is not None and parameter.kind in _BY_KEYWORD


_KEYWORD: Final = "call_context"
_BY_KEYWORD: Final = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
