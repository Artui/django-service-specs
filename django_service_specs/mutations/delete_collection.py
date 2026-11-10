from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django_service_specs.mutations.change_result import ModelT


def delete_collection(
    model: type[ModelT],
    *,
    soft_delete: Callable[[Any], None] | None = None,
) -> Callable[..., None]:
    """A service that deletes the resolved ``collection`` in one bulk delete."""

    def _service(*, collection: Any, **kwargs: Any) -> None:
        if soft_delete is not None:
            soft_delete(collection)
        else:
            collection.delete()

    return _service
