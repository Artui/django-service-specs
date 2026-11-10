from __future__ import annotations

from typing import Any, Protocol, TypeVar

InputT = TypeVar("InputT", contravariant=True)
InstanceT = TypeVar("InstanceT", contravariant=True)
ResultT = TypeVar("ResultT", covariant=True)


class UpdateService(Protocol[InputT, InstanceT, ResultT]):
    """The structural shape of a service that acts on a resolved row with validated input."""

    def __call__(self, *, instance: InstanceT, data: InputT, **extras: Any) -> ResultT: ...
