"""``sync_answer``: the one reading of a permission check's answer."""

from __future__ import annotations

import inspect
from typing import Any

from django.core.exceptions import ImproperlyConfigured


def sync_answer(answer: Any, *, asked: str) -> Any:
    """Return a permission check's ``answer``, refusing one that is still to be awaited.

    Read by the three ``authorize`` functions, so the class-level,
    object-level and scope-level checks cannot disagree about an answer that
    is not one, and by a transport that asks a check itself rather than
    through them: it reads the answer through this, so a coroutine fails
    closed there as it does in dispatch. A check is sync-only and its answer
    is read for truth. An ``async def`` method returns a coroutine, which is
    truthy, so read as it stands it would allow every call whatever the check
    meant. The spec refuses an ``async def`` method when it is built, but a
    method that hands back a coroutine from a plain ``def`` - a decorated
    ``async def``, a partial over one - looks sync until it answers, so the
    answer is checked here, where it is read. It fails closed: the call is
    refused with ``ImproperlyConfigured`` and never read as a pass. Any other
    answer comes back as it is. ``asked`` names the method, as
    ``Class.method``.

    A coroutine is closed first, so it is not left behind to warn that it was
    never awaited. Two disjuncts, each held in
    ``tests/authorization/test_sync_answer.py``:
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
