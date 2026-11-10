from __future__ import annotations

from types import ModuleType
from typing import Any

import pytest
from asgiref.sync import sync_to_async


async def books_closed() -> bool:
    """Awaited, unmet. Called sync, a coroutine, which is truthy."""
    return False


def count_hops(monkeypatch: pytest.MonkeyPatch, module: ModuleType) -> list[str]:
    """The name of every function ``module`` sends to the executor, as it sends them."""
    sent: list[str] = []

    def counting(fn: Any, *, thread_sensitive: bool) -> Any:
        sent.append(fn.__name__)
        return sync_to_async(fn, thread_sensitive=thread_sensitive)

    monkeypatch.setattr(module, "sync_to_async", counting)
    return sent
