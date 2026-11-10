from __future__ import annotations

import inspect
from typing import Any

from django.core.exceptions import ImproperlyConfigured


def sync_answer(answer: Any, *, asked: str) -> Any:
    """Return a permission check's ``answer``, refusing one that is still to be awaited."""
    if inspect.isawaitable(answer) or inspect.isasyncgen(answer):
        if inspect.iscoroutine(answer):
            answer.close()
        raise ImproperlyConfigured(
            f"{asked} answered with an awaitable ({type(answer).__name__}) where a bool was "
            "asked for. A permission check is sync-only and is never awaited, so the call "
            "is refused rather than allowed; declare the method with def."
        )
    return answer
