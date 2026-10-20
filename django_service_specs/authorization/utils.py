"""Helpers shared by everything that decides whether a principal may act at all.

``sync_answer`` is read by the three ``authorize`` functions, so the
class-level, object-level and scope-level checks cannot disagree about an
answer that is not one, and so is ``asked_with``, so they cannot disagree
about which check is handed the call's arguments."""

from __future__ import annotations

import inspect
import weakref
from collections.abc import Callable, Mapping
from types import FunctionType
from typing import Any, Final

from django.core.exceptions import ImproperlyConfigured


def sync_answer(answer: Any, *, asked: str) -> Any:
    """Return a permission check's ``answer``, refusing one that is still to be awaited.

    A check is sync-only and its answer is read for truth. An ``async def``
    method returns a coroutine, which is truthy, so read as it stands it would
    allow every call whatever the check meant. The spec refuses an ``async def``
    method when it is built, but a method that hands back a coroutine from a
    plain ``def`` - a decorated ``async def``, a partial over one - looks sync
    until it answers, so the answer is checked here, where it is read. It fails
    closed: the call is refused with ``ImproperlyConfigured`` and never read as
    a pass. ``asked`` names the method, as ``Class.method``.

    A coroutine is closed first, so it is not left behind to warn that it was
    never awaited. Two disjuncts, each held in
    ``tests/dispatch/test_authorize.py``'s ``TestAnAnswerThatIsNotAnAnswer``:
    ``test_an_awaitable_that_is_not_a_coroutine_is_refused`` fails without the
    first and ``test_an_async_generator_is_refused`` without the second, since
    an async generator is not awaitable and is truthy too.
    """
    if inspect.isawaitable(answer) or inspect.isasyncgen(answer):
        if inspect.iscoroutine(answer):
            answer.close()
        raise ImproperlyConfigured(
            f"{asked} answered with an awaitable ({type(answer).__name__}) where a bool was "
            "asked for. A permission check is sync-only and is never awaited, so the call "
            "is refused rather than allowed; declare the method with def."
        )
    return answer


def asked_with(check: Any, method: str, arguments: Mapping[str, Any] | None) -> dict[str, Any]:
    """The keywords to ask ``check``'s ``method`` with: ``arguments``, if it declares them.

    The base ``PermissionCheck`` methods declare no ``arguments``, so every
    check written without them keeps its signature and stays a
    valid override; a method that wants the call's arguments declares the
    keyword, and only a method that does is handed it. Read off
    ``getattr(check, method)``, the callable dispatch is about to call, so a
    callable set on the instance answers for itself
    (test_a_method_shadowed_on_the_instance_is_read_as_the_shadow), a mock
    patched over the method is asked as a check that never opted in
    (test_a_mock_patched_over_a_method_is_asked_as_before), a forwarding
    decorator as the method it wraps
    (test_a_forwarding_wrapper_answers_for_the_method_it_wraps), a method replaced
    after the class was defined is read as it now is
    (test_a_method_replaced_on_its_class_is_read_as_it_now_is), and an
    inherited one as its declaring class wrote it
    (test_a_subclass_inherits_the_declaration).
    """
    return {"arguments": arguments} if _declares_arguments(getattr(check, method)) else {}


def _declares_arguments(asked: Callable[..., Any]) -> bool:
    """Whether ``asked`` declares ``arguments``, cached only where that is safe.

    A method the class defines is cached under the function it binds, never
    under the bound method, which is made afresh on every lookup and would hold
    its check for the cache's life (test_a_check_is_not_kept_once_asked). Any
    other callable is read uncached: one set on an instance or patched in as a
    mock is as short-lived as its check
    (test_a_callable_set_on_the_instance_is_not_kept_once_asked), and a
    callable object with ``eq`` and no hash could not be a key at all
    (test_a_callable_the_class_holds_unhashed_is_read_by_its_own_signature).
    So the test is that ``__func__`` is a plain function, not merely present:
    ``MethodType`` binds any callable, and one binding such an object would
    reach the cache with no hash
    (test_a_method_binding_a_callable_object_is_read_uncached).
    """
    function = getattr(asked, "__func__", None)
    if isinstance(function, FunctionType):
        return _function_declares_arguments(function)
    return _names_arguments(asked)


# Keyed weakly on the function, so the entry goes with it: a check class a
# factory builds per call is freed with its last instance, and the cache does
# not grow with every class ever asked
# (test_a_class_built_at_runtime_is_not_kept_once_asked).
_DECLARES: Final[weakref.WeakKeyDictionary[FunctionType, bool]] = weakref.WeakKeyDictionary()


def _function_declares_arguments(function: FunctionType) -> bool:
    """``_names_arguments`` over a function a class defines, inspected once.

    A call asks each check up to twice, and checks share a class, so the
    signature is read once per function
    (test_a_class_defined_function_s_signature_is_inspected_once); it does not
    change while its function lives, and replacing the method on the class
    binds a different function, which is read afresh
    (test_a_method_replaced_on_its_class_is_read_as_it_now_is).
    """
    declares = _DECLARES.get(function)
    if declares is None:
        declares = _DECLARES[function] = _names_arguments(function)
    return declares


def _names_arguments(asked: Callable[..., Any]) -> bool:
    """Whether ``asked`` takes ``arguments`` by keyword, itself or by forwarding it.

    A walk down the ``__wrapped__`` chain ``functools.wraps`` leaves, one
    layer at a time, each read by its own signature - every layer is called
    in turn, so each must take the keyword or pass it on:

    - a layer naming ``arguments`` by keyword takes it, and the answer is
      yes (test_a_forwarding_wrapper_is_handed_them_where_the_method_it_wraps_declares_them,
      test_forwarding_layers_over_an_opted_in_method_are_handed_them);
    - a layer with no ``**kwargs`` would refuse it, and the answer is no,
      whatever lies beneath: a wrapper narrower than what it wraps
      (test_a_wrapper_narrower_than_the_method_it_wraps_is_read_as_the_wrapper),
      or one met lower down
      (test_a_forwarding_wrapper_over_a_narrower_one_is_handed_nothing);
    - a layer spreading ``**kwargs`` passes it on, so the walk steps to what
      it wraps; with nothing beneath, nothing that asked would receive it,
      and the answer is no (test_a_method_taking_only_keywords_is_handed_nothing,
      test_a_forwarding_wrapper_over_a_method_naming_none_is_handed_nothing).

    A layer with no signature to read ends it with no too (``_own_parameters``).
    A layer met twice ends the walk with no, since a chain that loops names
    nothing new (test_a_wrapped_chain_that_loops_is_handed_nothing; without
    that conjunct the test never finishes). The other conjunct stops the walk
    at the bottom of the chain: without it,
    test_a_decorator_without_wraps_answers_for_its_own_spread_alone fails.
    """
    layer: Any = asked
    walked: list[Any] = []
    while layer is not None and not any(layer is seen for seen in walked):
        walked.append(layer)
        parameters = _own_parameters(layer)
        if parameters is None:
            return False
        if _reached_by_keyword(parameters.get("arguments")):
            return True
        if not any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
        ):
            return False
        layer = getattr(layer, "__wrapped__", None)
    return False


def _own_parameters(layer: Any) -> Mapping[str, inspect.Parameter] | None:
    """``layer``'s own parameters, or ``None`` where it has no signature to read.

    A builtin, or a partial over one, has none (``ValueError``:
    test_a_callable_with_no_signature_is_handed_nothing,
    test_a_callable_with_no_signature_is_asked_as_before), nor has a
    ``__wrapped__`` that cannot be called (``TypeError``:
    test_a_wrapped_layer_that_is_not_callable_is_handed_nothing). Such a
    layer never declared ``arguments``, so it is read as not having opted
    in, and a check that never did is asked without them.
    """
    try:
        return inspect.signature(layer, follow_wrapped=False).parameters
    except (ValueError, TypeError):
        return None


def _reached_by_keyword(parameter: inspect.Parameter | None) -> bool:
    """Whether ``parameter`` is one a keyword ``arguments=`` reaches as the mapping itself.

    One branch to coverage, so each conjunct is held by its own test in
    ``tests/authorization/test_utils.py``:
    ``test_a_method_that_names_no_arguments_is_handed_nothing`` fails without
    the first, and
    ``test_a_parameter_named_arguments_that_no_keyword_reaches_is_handed_nothing``
    without the second (as does
    ``test_a_forwarding_wrapper_over_a_positional_only_arguments_is_handed_nothing``
    beneath a forwarding layer): a parameter of that name that is positional-only or
    variadic is not reached.
    """
    return parameter is not None and parameter.kind in (
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    )
