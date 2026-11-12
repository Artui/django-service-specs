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
    """``validator.parameters()``, handed ``call_context`` where it declares the keyword.

    Every ask inside one call passes that call's dict, the same object, so a
    Validator keyed on the dict describes one call one way. Every ask outside a
    call - registration, a schema, a describe-time reader - passes ``None``,
    unless a transport describing a spec hands a stamped dict with no call
    under way. Handed ``None``, the Validator is asked as it always was, with
    no keyword at all
    (test_an_opted_in_validator_asked_outside_a_call_is_handed_no_keyword).
    Otherwise the keyword is passed only to a ``parameters`` naming
    ``call_context`` itself (``_declares``), so a Validator that never
    declared it is asked as before
    (test_a_validator_declaring_no_call_context_is_asked_as_before).

    Dispatch asks every Validator through this, and so should a transport
    that asks one itself during a call - for the names of a ``many`` spec's
    rows, say - handing it the call's dict, so a Validator that opted in is
    described as dispatch describes it, whoever wrote it
    (TestThePublicName.test_an_opted_in_validator_is_handed_the_call_s_dict_through_it).
    """
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
