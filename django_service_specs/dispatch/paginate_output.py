"""``paginate_output`` - slice a list's rows into the one page a transport serves."""

from __future__ import annotations

from typing import Any, Final

from django.db.models.manager import BaseManager

from django_service_specs.selectors.utils import is_queryset
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

    A function a transport calls on a list result's ``value`` before presenting
    it, not a paging scheme: the names a caller pages by, and the ceiling a
    mount allows, are the transport's. A transport takes them off the call
    before the spec's closed argument set sees them, and bounds legitimately
    differ between two mounts of one spec. HTTP views do not page.

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
    with a ``DatabaseError`` this does not catch.

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
        # ``BaseManager`` rather than ``Manager``, because ``is_queryset``
        # counts every ``BaseManager`` and one built with
        # ``BaseManager.from_queryset`` is not a ``Manager``. Counted, and then
        # refused at the slice, without this: test_a_manager_is_paged_as_its_queryset
        # and test_a_manager_built_on_base_manager_is_paged_too.
        rows = rows.all()
    served_limit: int = max(1, DEFAULT_PAGE_SIZE if limit is None else limit)
    if max_page_size is not None:
        served_limit = min(served_limit, max_page_size)
    total: int = _count(rows)
    # Clamped against the ``totalPages`` the envelope will report, so the page
    # served is never one the same payload then says does not exist.
    served_page: int = min(max(1, 1 if page is None else page), max(1, -(-total // served_limit)))
    start: int = (served_page - 1) * served_limit
    return OutputPage(
        items=rows[start : start + served_limit],
        page=served_page,
        limit=served_limit,
        total=total,
    )


def _count(rows: Any) -> int:
    """How many rows there are, without evaluating a queryset.

    Told apart with ``is_queryset``, **not** ``hasattr(rows, "count")``:
    ``list`` and ``tuple`` have a ``count`` too, but it is ``count(value)`` and
    takes an argument, which would turn a list into an opaque ``count() takes
    exactly one argument``.
    """
    if is_queryset(rows):
        return int(rows.count())
    # One branch to coverage, so each condition is held by its own test, both
    # in test_something_that_cannot_be_both_counted_and_sliced_says_so:
    # ``sized-and-not-sliceable`` (the first) and ``sliceable-and-not-sized``
    # (the second).
    if hasattr(rows, "__len__") and hasattr(rows, "__getitem__"):
        return len(rows)  # a plain sequence, paged in memory
    raise TypeError(
        "A paginated selector must return a QuerySet or a sized, sliceable sequence "
        f"(list / tuple); got {type(rows).__name__}. Return a sliceable collection, "
        "or serve this selector unpaginated."
    )
