"""Helpers shared by everything that decides whether a principal may act at all.

``sync_answer`` is read by the three ``authorize`` functions, so the
class-level, object-level and scope-level checks cannot disagree about an
answer that is not one, and so is ``asked_with``, so they cannot disagree
about which check is handed the call's arguments. The deactivated rule is read in three places: dispatch, refusing the principal
it was handed; ``resolve_principal``, refusing the row an identifier named; and
the HTTP entry points, refusing ``request.user`` before the request is read.
It is written once here so the three cannot disagree about who is refused.
Nothing here imports anything that imports dispatch, so each of the three can
read it without a cycle.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Mapping
from types import FunctionType
from typing import Any

from django.core.exceptions import ImproperlyConfigured


def is_deactivated(principal: Any) -> bool:
    """True for an authenticated principal whose ``is_active`` is false.

    ``ModelBackend`` never logs a deactivated account in, but
    ``AllowAllUsersModelBackend`` and a project's own backend may, and a
    transport that holds a user object of its own may hand one over long after
    it was deactivated. The kernel's rule is that a deactivated principal never
    acts, whichever way it arrived.

    Both attributes are read with ``getattr`` rather than assumed, because a
    principal is whatever a transport hands over:

    - **No ``is_active`` reads as active**, as ``ModelBackend`` reads it: a
      custom user model is not required to declare the field.
    - **Anonymous is not deactivated.** ``AnonymousUser.is_active`` is false,
      so the rule asks about authenticated principals alone, and anonymous goes
      on to the permission check, which is what decides whether anonymous may
      act. A principal with no ``is_authenticated`` is not anonymous, so it is
      read as authenticated and refused only when it says it is inactive.

    Each condition is held by its own test in
    ``tests/authorization/test_utils.py``:
    ``test_anonymous_is_not_deactivated`` fails without the first and
    ``test_an_active_user_is_not_deactivated`` without the second.
    """
    return bool(getattr(principal, "is_authenticated", True)) and not getattr(
        principal, "is_active", True
    )


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
    check written before the channel existed keeps its signature and stays a
    valid override; a method that wants the call's arguments declares the
    keyword, and only a method that does is handed it. Read off
    ``getattr(check, method)``, the callable dispatch is about to call, so a
    callable set on the instance answers for itself
    (test_a_method_shadowed_on_the_instance_is_read_as_the_shadow), a mock
    patched over the method is asked as a check that never opted in
    (test_a_mock_patched_over_a_method_is_asked_as_before), a method replaced
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
    """
    function = getattr(asked, "__func__", None)
    if isinstance(function, FunctionType):
        return _function_declares_arguments(function)
    return _names_arguments(asked)


@functools.cache
def _function_declares_arguments(function: FunctionType) -> bool:
    """``_names_arguments`` over a function a class defines, inspected once.

    A call asks each check up to twice, and a signature does not change while
    its function lives; replacing the method on the class binds a different
    function, which is read afresh
    (test_a_method_replaced_on_its_class_is_read_as_it_now_is).
    """
    return _names_arguments(function)


def _names_arguments(asked: Callable[..., Any]) -> bool:
    """Whether ``asked`` names a parameter ``arguments`` that can be passed by keyword.

    By name alone: a method spreading ``**kwargs`` is not handed it, since a
    wrapper forwarding them to a method that never declared ``arguments``
    would pass on a keyword that method refuses
    (test_a_method_taking_only_keywords_is_handed_nothing). Nor is a
    parameter of that name that is positional-only or variadic, which no
    keyword reaches as the mapping itself
    (test_a_parameter_named_arguments_that_no_keyword_reaches_is_handed_nothing).

    The callable's own signature, not the one ``functools.wraps`` points
    ``__wrapped__`` at: the wrapper is what is called, so a wrapper narrower
    than the method it wraps is not handed a keyword it would refuse
    (test_a_wrapper_narrower_than_the_method_it_wraps_is_read_as_the_wrapper),
    and one spreading ``**kwargs`` is handed nothing, as any method spreading
    them is (test_a_wrapper_spreading_its_keywords_is_handed_nothing_whatever_it_wraps).

    One branch to coverage, so each conjunct is held by its own test in
    ``tests/authorization/test_utils.py``:
    ``test_a_method_that_names_no_arguments_is_handed_nothing`` fails without
    the first, and
    ``test_a_parameter_named_arguments_that_no_keyword_reaches_is_handed_nothing``
    without the second.
    """
    parameter = inspect.signature(asked, follow_wrapped=False).parameters.get("arguments")
    return parameter is not None and parameter.kind in (
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    )
