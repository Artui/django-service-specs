from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django_service_specs.mutations.change_result import ModelT


def delete_collection(
    model: type[ModelT],
    *,
    soft_delete: Callable[[Any], None] | None = None,
) -> Callable[..., None]:
    """A service that deletes the resolved ``collection`` in one bulk delete, and returns ``None``.

    Pairs with a spec's ``collection_selector_spec``, whose rows dispatch
    seeds into the pool as ``collection``. The service a bulk delete would
    otherwise write by hand:

        def delete_books(*, collection: QuerySet[Book], **_: Any) -> None:
            collection.delete()

    ``collection.delete()`` is Django's bulk delete, which runs each foreign
    key's ``on_delete`` and sends ``pre_delete`` and ``post_delete`` for every
    row, as a single row's delete does. An empty collection deletes nothing, so
    running the operation twice is harmless. ``model`` is not read,
    as in [`delete_model`][django_service_specs.services.delete_model.delete_model].

    ``soft_delete`` is called with the ``collection`` *instead of* ``delete()``,
    as in ``lambda rows: rows.update(is_archived=True)``. The service opens no
    transaction, since dispatch runs it inside one, and absorbs the rest of
    the pool.
    """

    def _service(*, collection: Any, **kwargs: Any) -> None:
        if soft_delete is not None:
            soft_delete(collection)
        else:
            collection.delete()

    return _service
