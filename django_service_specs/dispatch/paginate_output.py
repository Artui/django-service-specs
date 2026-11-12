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
    """Slice ``rows`` into the page a transport serves.

    A function a transport calls on a paged spec's result ``value`` before
    presenting it, not a paging scheme: the names a caller pages by, and the
    ceiling a mount allows, are the transport's. A transport takes them off the
    call before the spec's closed argument set sees them, and bounds
    legitimately differ between two mounts of one spec.

    Whether to page is read off the spec, never off the result's ``kind``: a
    ``LIST`` selector spec, or a service spec whose output selector is a
    ``LIST``, is paged, and
    [`spec_output_schema`][django_service_specs.schema.spec_output_schema.spec_output_schema]
    describes it as the envelope under ``paginate=True``. A ``many`` or
    ``returns_many`` service spec's result is ``kind="list"`` too, and is never
    paged: it is every row the service returned, which its output schema
    describes as a bare array whatever ``paginate`` says.

    ``page`` and ``limit`` default to 1 and
    [`DEFAULT_PAGE_SIZE`][django_service_specs.dispatch.paginate_output.DEFAULT_PAGE_SIZE].
    Out-of-range values clamp at **both** ends - ``limit`` down to
    ``max_page_size`` and up to 1, ``page`` up to 1 and down to the last page
    that exists - and the clamps are not silent the way truncating an unpaged
    result would be: ``totalPages`` and ``hasNext`` are computed from the
    clamped ``limit``, and the returned ``page`` is the one actually served. A
    caller that asked for 500 rows and got 100, or for page 10 of 3, is told
    what it received.

    Both values are taken already parsed. Turning an untyped argument into an
    integer is where transports legitimately differ - a public endpoint clamps
    a malformed value and answers, an in-process toolset can hand a model its
    mistake back and ask again - and that is a policy about bad input, not
    about what a page is.

    The upper clamp on ``page`` is why ``total`` is counted **before** the
    slice: ``(page - 1) * limit`` on an unclamped page is an arbitrarily large
    SQL ``OFFSET``, which a backend either scans towards or refuses outright
    with a ``DatabaseError`` this does not catch. No slice is longer than
    ``total`` for the same reason, so a ``limit`` past any integer a database
    holds, which no ``max_page_size`` bounded, still serves every row; the
    page reports the ``limit`` asked for.

    A queryset is counted with ``COUNT`` and sliced lazily, so the page's
    ``items`` is still a queryset: present them, as
    [`present`][django_service_specs.dispatch.present.present] does a list,
    and the page is read once. A manager - any ``BaseManager``, so one built
    with ``BaseManager.from_queryset`` too - is paged as its ``.all()``, since
    it counts and cannot be sliced.

    Raises:
        TypeError: ``rows`` is neither a queryset nor a sized, sliceable
            sequence, so there is nothing to count and nothing to slice.
    """
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
