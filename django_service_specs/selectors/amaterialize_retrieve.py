"""``amaterialize_retrieve`` - ``materialize_retrieve``, from a coroutine."""

from __future__ import annotations

from typing import Any

from django_service_specs.selectors.is_queryset import is_queryset


async def amaterialize_retrieve(result: Any) -> Any:
    """Async twin of ``materialize_retrieve``, awaiting ``.afirst()``.

    Separate because the materialization *is* the query: ``.first()`` would
    block the event loop, and raises ``SynchronousOnlyOperation`` there. The
    same rule otherwise; keep the two in step.
    """
    return await result.afirst() if is_queryset(result) else result
