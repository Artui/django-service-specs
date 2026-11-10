from __future__ import annotations

from typing import Any, Protocol, TypeVar

InputT = TypeVar("InputT", contravariant=True)
InstanceT = TypeVar("InstanceT", contravariant=True)
ResultT = TypeVar("ResultT", covariant=True)


class DeleteService(Protocol[InputT, InstanceT, ResultT]):
    """The structural shape of a service that acts on a resolved row, input optional."""

    def __call__(self, *, instance: InstanceT, data: InputT = ..., **extras: Any) -> ResultT: ...
