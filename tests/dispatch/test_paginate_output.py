"""Tests for ``paginate_output``.

Ported from the shaper's tests where it was first written, so each case pins
something that implementation had already learned: the clamps at both ends,
the count before the slice, and the ``.count`` that is not a count.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
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


def test_a_limit_over_the_ceiling_is_clamped_down() -> None:
    page = paginate_output(ROWS, limit=500, max_page_size=100)

    assert page.limit == 100
    assert len(page.items) == 100


def test_a_limit_under_the_ceiling_is_untouched() -> None:
    assert paginate_output(ROWS, limit=25, max_page_size=100).limit == 25


def test_no_ceiling_leaves_a_large_limit_alone() -> None:
    assert paginate_output(ROWS, limit=500).limit == 500


def test_the_ceiling_also_bounds_the_default_size() -> None:
    assert paginate_output(ROWS, max_page_size=10).limit == 10


@pytest.mark.parametrize("limit", [0, -5])
def test_a_limit_below_one_is_clamped_up(limit: int) -> None:
    """Not refused: a page of no rows is a page nobody can page through."""
    assert paginate_output(ROWS, limit=limit).limit == 1


@pytest.mark.parametrize("page", [0, -3])
def test_a_page_below_one_is_clamped_up(page: int) -> None:
    assert paginate_output(ROWS, page=page, limit=10).page == 1


def test_a_page_past_the_end_clamps_to_the_last_one_that_exists() -> None:
    page = paginate_output(ROWS, page=99, limit=100)

    assert (page.page, page.total_pages, page.has_next) == (3, 3, False)
    assert page.items == ROWS[200:]


def test_a_page_inside_the_range_is_untouched() -> None:
    page = paginate_output(ROWS, page=2, limit=100)

    assert (page.page, page.has_next) == (2, True)
    assert page.items == ROWS[100:200]


def test_an_empty_result_is_one_empty_page() -> None:
    """Not zero pages: the page served is 1, so saying it does not exist
    contradicts the payload it arrives with."""
    page = paginate_output([], page=7, limit=10)

    assert (page.page, page.total, page.total_pages, page.has_next) == (1, 0, 1, False)
    assert list(page.items) == []


def test_a_partial_last_page_is_still_the_last_page() -> None:
    page = paginate_output(ROWS, page=3, limit=100)

    assert (page.total_pages, page.has_next, len(page.items)) == (3, False, 50)


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
    well. Testing ``Manager`` counted it and then refused it at the slice."""
    ada = make_user("ada")
    for title in ("a", "b", "c"):
        Note.objects.create(owner=ada, title=title)
    manager: Any = BaseManager.from_queryset(QuerySet)()
    manager.model = Note

    page = paginate_output(manager, limit=2)

    assert (page.total, page.page, page.has_next) == (3, 1, True)
    assert len(page.items) == 2
