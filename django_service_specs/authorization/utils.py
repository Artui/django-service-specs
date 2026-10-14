"""Helpers shared by everything that decides whether a principal may act at all.

``sync_answer`` is read by the three ``authorize`` functions, so the
class-level, object-level and scope-level checks cannot disagree about an
answer that is not one. The deactivated rule is read in three places: dispatch, refusing the principal
it was handed; ``resolve_principal``, refusing the row an identifier named; and
the HTTP entry points, refusing ``request.user`` before the request is read.
It is written once here so the three cannot disagree about who is refused.
Nothing here imports anything that imports dispatch, so each of the three can
read it without a cycle.

``compiled_spec`` is ``kernel_spec`` for the modules here, which the spec
modules import and so cannot import a spec module at their top: the three
``authorize`` functions and ``Grant.covers`` read a declaration of another
library's through it, as every other entry point does.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ImproperlyConfigured

if TYPE_CHECKING:
    # Annotation-only, for the reason permission_check.py gives.
    from django_service_specs.specs.selector_spec import SelectorSpec
    from django_service_specs.specs.service_spec import ServiceSpec
    from django_service_specs.specs.spec_source import SpecSource


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
    ``tests/authorization/test_authorize.py``'s ``TestAnAnswerThatIsNotAnAnswer``:
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


def compiled_spec(spec: ServiceSpec | SelectorSpec | SpecSource) -> ServiceSpec | SelectorSpec:
    """``spec`` as a spec of this package's, as ``kernel_spec`` answers it.

    For the authorization modules alone, which cannot import ``kernel_spec`` at
    their top; every other module imports it directly.
    """
    # A proven cycle, and the one function-local import in this subpackage.
    # ``kernel_spec`` recognizes a spec by its class, so its module imports
    # ``ServiceSpec`` and ``SelectorSpec``; their modules import
    # ``permission_check`` for the ``permissions`` field, which loads this
    # subpackage's ``__init__``, which loads ``grant`` and the three
    # ``authorize`` functions. A top-level import of ``kernel_spec`` in any of
    # those fails with ``SelectorSpec`` half-initialized. By the time a grant
    # or a check is asked anything, every spec module has finished loading, so
    # this resolves from ``sys.modules`` and runs nothing.
    from django_service_specs.specs.spec_source import kernel_spec

    return kernel_spec(spec)
