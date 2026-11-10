from __future__ import annotations

from typing import Any

from django_service_specs.selectors.is_queryset import is_queryset


async def amaterialize_retrieve(result: Any) -> Any:
    """Async twin of ``materialize_retrieve``, awaiting ``.afirst()``."""
    return await result.afirst() if is_queryset(result) else result
