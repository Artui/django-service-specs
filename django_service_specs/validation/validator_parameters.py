"""How the kernel asks a Validator what it takes, inside a call or outside one."""

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

    Every ask inside one call passes that call's dict, the same object, and
    every ask outside a call - registration, a schema, a describe-time
    reader - passes ``None``, unless a transport describing a spec hands a
    stamped dict with no call under way, so a Validator keyed on the dict
    describes one call one way. Handed ``None``, the Validator is asked as it always was,
    with no keyword at all
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
    # Widened, since the base method declares no keyword and only an opted-in
    # subclass's takes one, and the keyword is passed only where ``_declares`` read it.
    asked = cast(Callable[..., Parameters], validator.parameters)
    if call_context is not None and _declares(asked):
        return asked(call_context=call_context)
    return asked()


def _declares(asked: Callable[..., Any]) -> bool:
    """Whether ``asked`` names ``call_context`` as a parameter a keyword reaches, by its own signature.

    Its own signature only, never the ``__wrapped__`` chain ``functools.wraps``
    leaves: a wrapper is what is called, so a wrapper not naming the keyword
    is asked without it, whatever the function beneath declares
    (test_a_wrapper_not_naming_the_keyword_is_handed_nothing). A ``**kwargs``
    spread names nothing (test_a_kwargs_only_parameters_is_handed_nothing,
    test_a_mock_parameters_is_handed_nothing).

    A method the class defines is read once, cached under the function it
    binds rather than the bound method, which is made afresh on every lookup
    (test_the_signature_is_read_once_per_function). Any other callable is
    read uncached: one set on an instance or patched in is as short-lived as
    its Validator, and a callable object need not be hashable. The test is
    that ``__func__`` is a plain function, since ``MethodType`` binds any
    callable (test_a_method_binding_an_unhashable_callable_is_handed_the_call_s_dict).
    """
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
    """``_declares``, read off ``asked``'s signature.

    A callable with no signature to read (``ValueError`` for a builtin,
    ``TypeError`` for a ``__signature__`` that is not one) never declared the
    keyword, so it is asked as it was before
    (test_a_parameters_with_no_signature_is_asked_as_before for ``TypeError``,
    test_a_parameters_whose_signature_read_raises_value_error_is_asked_as_before
    for ``ValueError``).

    One arc to coverage, each part held by its own test: without the first
    conjunct a ``parameters`` naming no ``call_context`` raises on ``.kind``
    (test_a_validator_declaring_no_call_context_is_asked_as_before); without
    the second a positional-only one is handed a keyword it cannot take
    (test_a_positional_only_call_context_is_handed_nothing); and a
    positional-or-keyword one is reached as a keyword-only one is
    (test_a_validator_declaring_call_context_is_handed_the_call_s_dict[_PositionalOrKeyword]).
    """
    try:
        parameter = inspect.signature(asked, follow_wrapped=False).parameters.get(_KEYWORD)
    except (ValueError, TypeError):
        return False
    return parameter is not None and parameter.kind in _BY_KEYWORD


_KEYWORD: Final = "call_context"
_BY_KEYWORD: Final = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
