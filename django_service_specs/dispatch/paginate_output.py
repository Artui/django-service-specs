from __future__ import annotations

from typing import Any, Final

from django.db.models.manager import BaseManager

from django_service_specs.selectors.is_queryset import is_queryset
from django_service_specs.types.output_page import OutputPage

DEFAULT_PAGE_SIZE: Final[int] = 100
"""Rows per page when the caller asks for a page and names no size."""


def paginate_output(
    rows: Any,
    *,
    page: int | None = None,
    limit: int | None = None,
    max_page_size: int | None = None,
) -> OutputPage:
    """Slice ``rows`` into the page a transport serves."""
    if isinstance(rows, BaseManager):
        rows = rows.all()
    served_limit: int = max(1, DEFAULT_PAGE_SIZE if limit is None else limit)
    if max_page_size is not None:
        served_limit = min(served_limit, max_page_size)
    total: int = _count(rows)
    served_page: int = min(max(1, 1 if page is None else page), max(1, -(-total // served_limit)))
    start: int = (served_page - 1) * served_limit
    length: int = min(served_limit, total)
    return OutputPage(
        items=rows[start : start + length],
        page=served_page,
        limit=served_limit,
        total=total,
    )


def _count(rows: Any) -> int:
    """How many rows there are, without evaluating a queryset."""
    if is_queryset(rows):
        return int(rows.count())
    if hasattr(rows, "__len__") and hasattr(rows, "__getitem__"):
        return len(rows)
    raise TypeError(
        "A paginated selector must return a QuerySet or a sized, sliceable sequence "
        f"(list / tuple); got {type(rows).__name__}. Return a sliceable collection, "
        "or serve this selector unpaginated."
    )
