from __future__ import annotations

from typing import Any, Protocol, TypeVar

ResultT = TypeVar("ResultT", covariant=True)


class RetrieveSelector(Protocol[ResultT]):
    """The structural shape of the ``selector`` of a ``RETRIEVE`` ``SelectorSpec``."""

    def __call__(self, **extras: Any) -> ResultT | None: ...
