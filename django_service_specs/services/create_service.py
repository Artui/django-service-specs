from __future__ import annotations

from typing import Any, Protocol, TypeVar

InputT = TypeVar("InputT", contravariant=True)
ResultT = TypeVar("ResultT", covariant=True)


class CreateService(Protocol[InputT, ResultT]):
    """The structural shape of a service that takes validated input and no target."""

    def __call__(self, *, data: InputT, **extras: Any) -> ResultT: ...
