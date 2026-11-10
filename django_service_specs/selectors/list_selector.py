from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol, TypeVar

ResultT = TypeVar("ResultT", covariant=True)


class ListSelector(Protocol[ResultT]):
    """The structural shape of the ``selector`` of a ``LIST`` ``SelectorSpec``."""

    def __call__(self, **extras: Any) -> Iterable[ResultT]: ...
