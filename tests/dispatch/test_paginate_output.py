"""Tests for ``paginate_output``.

Each case pins a rule a page has to hold: the clamps at both ends, the count
before the slice, and the ``.count`` that is not a count.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from asgiref.sync import sync_to_async
from django.db.models import QuerySet
from django.db.models.manager import BaseManager

from django_service_specs.dispatch.paginate_output import DEFAULT_PAGE_SIZE, paginate_output
from tests.dispatch.utils import make_user
from tests.dispatch_app.models import Note

ROWS = list(range(250))


def test_defaults_to_the_first_page_at_the_default_size() -> None:
    page = paginate_output(ROWS)

    assert (page.page, page.limit, page.total) == (1, DEFAULT_PAGE_SIZE, 250)
    assert page.items == ROWS[:100]


def test_the_default_size_is_a_hundred_rows() -> None:
    assert DEFAULT_PAGE_SIZE == 100


@pytest.mark.parametrize(
    ("asked", "expected"),
    [
        pytest.param({"limit": 500, "max_page_size": 100}, 100, id="over-the-ceiling-clamps-down"),
        pytest.param({"limit": 25, "max_page_size": 100}, 25, id="under-the-ceiling-untouched"),
        pytest.param({"limit": 500}, 500, id="no-ceiling-leaves-a-large-limit-alone"),
        pytest.param({"max_page_size": 10}, 10, id="the-ceiling-bounds-the-default-size"),
        # Not refused: a page of no rows is a page nobody can page through.
        pytest.param({"limit": 0}, 1, id="zero-clamps-up"),
        pytest.param({"limit": -5}, 1, id="negative-clamps-up"),
    ],
)
def test_the_limit_served(asked: dict[str, int], expected: int) -> None:
    page = paginate_output(ROWS, **asked)

    assert page.limit == expected
    assert len(page.items) == min(expected, len(ROWS))


@pytest.mark.parametrize(
    ("asked", "expected"),
    [
        pytest.param(
            {"page": 99, "limit": 100},
            (3, 3, False, ROWS[200:]),
            id="past-the-end-clamps-to-the-last-that-exists",
        ),
        pytest.param({"page": 2, "limit": 100}, (2, 3, True, ROWS[100:200]), id="inside-the-range"),
        pytest.param(
            {"page": 3, "limit": 100}, (3, 3, False, ROWS[200:]), id="a-partial-last-page"
        ),
        pytest.param({"page": 0, "limit": 10}, (1, 25, True, ROWS[:10]), id="zero-clamps-up"),
        pytest.param({"page": -3, "limit": 10}, (1, 25, True, ROWS[:10]), id="negative-clamps-up"),
    ],
)
def test_the_page_served(asked: dict[str, int], expected: tuple[Any, ...]) -> None:
    page = paginate_output(ROWS, **asked)

    assert (page.page, page.total_pages, page.has_next, page.items) == expected


def test_an_empty_result_is_one_empty_page() -> None:
    """Not zero pages: the page served is 1, so saying it does not exist
    contradicts the payload it arrives with."""
    page = paginate_output([], page=7, limit=10)

    assert (page.page, page.total, page.total_pages, page.has_next) == (1, 0, 1, False)
    assert list(page.items) == []


@pytest.mark.django_db
def test_a_queryset_is_counted_and_sliced_rather_than_evaluated() -> None:
    owner = make_user("ada")
    Note.objects.bulk_create([Note(owner=owner, title=f"n{index}") for index in range(5)])

    page = paginate_output(Note.objects.order_by("pk"), page=2, limit=2)

    assert (page.total, page.page, page.total_pages, page.has_next) == (5, 2, 3, True)
    # Still a queryset: the slice is an ``OFFSET``/``LIMIT`` the caller's
    # rendering evaluates, not rows read here.
    assert page.items.query.low_mark == 2
    assert [note.title for note in page.items] == ["n2", "n3"]


def test_a_tuple_is_paginated_in_memory() -> None:
    page = paginate_output(tuple(ROWS), page=2, limit=100)

    assert page.total == 250
    assert page.items == tuple(ROWS[100:200])


def test_a_list_is_not_mistaken_for_a_queryset_by_its_count_attribute() -> None:
    """``list.count`` exists and takes an argument, so discriminating on
    ``hasattr(rows, "count")`` would answer an opaque ``count() takes exactly
    one argument`` for a list."""
    assert hasattr(ROWS, "count")

    assert paginate_output(ROWS, limit=10).total == 250


def _generator() -> Iterator[int]:
    yield 1


class _Indexable:
    """Sliceable and not sized: there is nothing to count."""

    def __getitem__(self, index: Any) -> Any:
        return []


@pytest.mark.parametrize(
    "rows",
    [
        pytest.param(_generator(), id="neither-sized-nor-sliceable"),
        # Each of the next two holds one condition of the sequence check: a set
        # is sized and cannot be sliced, ``_Indexable`` slices and has no size.
        pytest.param({1, 2, 3}, id="sized-and-not-sliceable"),
        pytest.param(_Indexable(), id="sliceable-and-not-sized"),
    ],
)
def test_something_that_cannot_be_both_counted_and_sliced_says_so(rows: Any) -> None:
    with pytest.raises(TypeError, match="QuerySet or a sized, sliceable sequence"):
        paginate_output(rows)


@pytest.mark.django_db
def test_a_manager_is_paged_as_its_queryset() -> None:
    # A Manager counts and cannot be sliced, so it is paged as ``.all()``.
    ada = make_user("ada")
    for title in ("a", "b", "c"):
        Note.objects.create(owner=ada, title=title)

    page = paginate_output(Note.objects, limit=2)

    assert (len(list(page.items)), page.total, page.has_next) == (2, 3, True)


@pytest.mark.django_db
def test_a_manager_built_on_base_manager_is_paged_too() -> None:
    """``BaseManager.from_queryset`` builds a manager that is not a ``Manager``,
    and ``is_queryset`` counts it like one, so it is paged as its ``.all()`` as
    well."""
    ada = make_user("ada")
    for title in ("a", "b", "c"):
        Note.objects.create(owner=ada, title=title)
    manager: Any = BaseManager.from_queryset(QuerySet)()
    manager.model = Note

    page = paginate_output(manager, limit=2)

    assert (page.total, page.page, page.has_next) == (3, 1, True)
    assert len(page.items) == 2


def _five_notes() -> None:
    owner = make_user("ada")
    Note.objects.bulk_create([Note(owner=owner, title=f"n{index}") for index in range(5)])


@pytest.mark.django_db
@pytest.mark.parametrize("limit", [2**63, 2**70])
def test_a_limit_past_any_integer_column_serves_every_row(limit: int) -> None:
    # With no ceiling, a slice ending at the limit itself would be a ``LIMIT``
    # past 64 bits, which the database refuses as ``datatype mismatch``. The
    # page served ends at the rows counted, and the limit reported is the one
    # asked for.
    _five_notes()

    page = paginate_output(Note.objects.order_by("pk"), limit=limit)

    assert [note.title for note in page.items] == ["n0", "n1", "n2", "n3", "n4"]
    assert (page.page, page.limit, page.total_pages, page.has_next) == (1, limit, 1, False)


@pytest.mark.django_db
def test_a_page_past_any_integer_column_never_reaches_the_offset() -> None:
    # The page clamps to the last one that exists before the offset is
    # computed, so the offset stays inside the rows counted.
    _five_notes()

    page = paginate_output(Note.objects.order_by("pk"), page=2**70, limit=2)

    assert page.page == 3
    assert [note.title for note in page.items] == ["n4"]


@pytest.mark.django_db(transaction=True)
async def test_a_limit_past_any_integer_column_serves_every_row_read_async() -> None:
    await sync_to_async(_five_notes)()

    page = await sync_to_async(paginate_output)(Note.objects.order_by("pk"), limit=2**70)

    assert [note.title async for note in page.items] == ["n0", "n1", "n2", "n3", "n4"]
