from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Selector(Protocol):
    """Any callable returning a queryset, a list or one object."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any: ...
