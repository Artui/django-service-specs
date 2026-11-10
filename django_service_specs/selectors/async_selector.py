from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AsyncSelector(Protocol):
    """The ``async def`` sibling of ``Selector``."""

    async def __call__(self, *args: Any, **kwargs: Any) -> Any: ...
