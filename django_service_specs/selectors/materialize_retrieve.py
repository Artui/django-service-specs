"""``materialize_retrieve`` - a RETRIEVE selector's return, as its row."""

from __future__ import annotations

from typing import Any

from django_service_specs.selectors.is_queryset import is_queryset


def materialize_retrieve(result: Any) -> Any:
    """Collapse a RETRIEVE selector's return to the single instance, or ``None``.

    The one definition of what ``kind=RETRIEVE`` means once the selector has
    run: a queryset materializes through ``.first()`` - so an author can write
    ``selector=lambda *, pk: Model.objects.filter(pk=pk)`` and still get the
    spec's shaping applied first - and anything else passes through as the
    resolved object. What each caller does with a ``None`` differs; how the
    value is arrived at does not.

    Exported for a transport that runs a RETRIEVE selector without
    ``dispatch``, so the row it checks or presents is the row dispatch would
    have resolved. Blocks on the query, so call ``amaterialize_retrieve``
    from a coroutine.
    """
    return result.first() if is_queryset(result) else result
