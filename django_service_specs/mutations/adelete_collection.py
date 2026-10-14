from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from django_service_specs.mutations.change_result import ModelT


def adelete_collection(
    model: type[ModelT],
    *,
    soft_delete: Callable[[Any], Awaitable[None]] | None = None,
) -> Callable[..., Awaitable[None]]:
    """The async twin of [`delete_collection`][django_service_specs.mutations.delete_collection.delete_collection].

    Deletes with ``await collection.adelete()``. ``soft_delete`` is an
    ``async def`` called with the ``collection`` in its place.
    """

    async def _service(*, collection: Any, **kwargs: Any) -> None:
        if soft_delete is not None:
            await soft_delete(collection)
        else:
            await collection.adelete()

    return _service
