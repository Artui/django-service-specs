"""The batching presenter's example on the declaring page, run.

Each test is a statement the page makes about ``docs/examples/presenting_rows.py``.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext

from django_service_specs import DispatchResult, PresentationContext, present
from docs.examples import presenting_rows
from tests.adapter_app.models import Author, Book, Edition

pytestmark = pytest.mark.django_db


@pytest.fixture
def ada() -> Any:
    return get_user_model().objects.create_user(username="ada")


@pytest.fixture
def books() -> list[Book]:
    author = Author.objects.create(name="Le Guin")
    made = [
        Book.objects.create(author=author, title=title, price=Decimal("9.99"))
        for title in ("Always Coming Home", "Lathe of Heaven", "The Dispossessed")
    ]
    for number in (1, 2):
        Edition.objects.create(book=made[0], number=number)
    Edition.objects.create(book=made[2], number=1)
    return made


def test_a_page_s_rows_carry_their_counts(ada: Any, books: list[Book]) -> None:
    assert presenting_rows.first_page(ada, limit=2) == [
        {"id": books[0].pk, "title": "Always Coming Home", "editions": 2},
        {"id": books[1].pk, "title": "Lathe of Heaven", "editions": 0},
    ]


@pytest.mark.parametrize("limit", [1, 3])
def test_the_count_is_one_query_however_many_rows_the_page_holds(
    ada: Any, books: list[Book], limit: int
) -> None:
    """Three queries at any page size: the pager's count of the catalogue, the
    page's rows, then every edition count at once, grouped by book."""
    with CaptureQueriesContext(connection) as queries:
        rows = presenting_rows.first_page(ada, limit=limit)

    assert len(rows) == limit
    grouped = ["GROUP BY" in query["sql"] for query in queries.captured_queries]
    assert grouped == [False, False, True]


def test_one_book_alone_is_a_batch_of_one_under_the_call_s_context(
    ada: Any, books: list[Book]
) -> None:
    seen: list[Any] = []

    class Recording(presenting_rows.BooksWithEditions):
        def presented_rows(self, values: Any, context: Any) -> Any:
            seen.append((values, context))
            return super().presented_rows(values, context)

    spec = replace(presenting_rows.books_spec, presenter=Recording())
    context = PresentationContext(ada)

    rendered = present(spec, DispatchResult("instance", books[2], context=context))

    assert rendered == {"id": books[2].pk, "title": "The Dispossessed", "editions": 1}
    assert seen == [((books[2],), context)]
    assert Recording().present(books[0])["editions"] == 2
