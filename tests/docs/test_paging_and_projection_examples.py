"""The paging and projection page's example, run.

Each test is a statement the page makes about
``docs/examples/paging_and_projection.py``. The page's JSON blocks are read
back and compared with what the example returns, so neither can drift from the
other.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured

from django_service_specs import FieldAudience, FieldMarking, audience_projection_for_spec
from docs.examples import paging_and_projection
from tests.adapter_app.models import Author, Book, Status

ROOT = Path(__file__).resolve().parents[2]


def json_blocks() -> list[Any]:
    page = (ROOT / "docs" / "paging-and-projection.md").read_text()
    return [json.loads(block) for block in re.findall(r"```json\n(.*?)```", page, re.DOTALL)]


SCHEMA, PAGE, WITH_AUTHORS, OVER_HTTP = json_blocks()


@pytest.fixture
def ada() -> Any:
    return get_user_model().objects.create_user(username="ada")


@pytest.fixture
def books() -> list[Book]:
    le_guin = Author.objects.create(name="Ursula K. Le Guin")
    return [
        Book.objects.create(author=le_guin, title=title, price=Decimal("9.99"), status=status)
        for title, status in [
            ("The Dispossessed", Status.PUBLISHED),
            ("The Lathe of Heaven", Status.DRAFT),
            ("A Wizard of Earthsea", Status.PUBLISHED),
        ]
    ]


def as_stored(payload: dict[str, Any], book: Book) -> dict[str, Any]:
    """A block's row with the identifiers this database assigned."""
    stored = {**payload, "id": book.pk}
    if "author_id" in payload:
        stored["author_id"] = book.author_id
    return stored


def test_the_schema_is_the_one_the_page_shows() -> None:
    assert paging_and_projection.output_schema == SCHEMA


@pytest.mark.django_db
class TestServingAPage:
    def test_page_two_is_the_one_the_page_shows(self, ada: Any, books: list[Book]) -> None:
        served = paging_and_projection.list_books_tool(ada, page=2, limit=2)

        assert served == {**PAGE, "items": [as_stored(PAGE["items"][0], books[2])]}

    def test_only_the_count_and_the_page_are_read(
        self, ada: Any, books: list[Book], django_assert_num_queries: Any
    ) -> None:
        with django_assert_num_queries(2) as captured:
            paging_and_projection.list_books_tool(ada, page=2, limit=2)

        count, rows = (query["sql"] for query in captured.captured_queries)
        assert "COUNT(" in count
        assert "LIMIT 2 OFFSET 2" in rows

    def test_a_clamped_request_is_told_what_it_was_served(
        self, ada: Any, books: list[Book]
    ) -> None:
        served = paging_and_projection.list_books_tool(ada, page=10, limit=500)

        assert (served["page"], served["totalPages"], served["hasNext"]) == (1, 1, False)
        assert len(served["items"]) == 3

    def test_the_ceiling_is_the_mounts(self, ada: Any, books: list[Book]) -> None:
        more = paging_and_projection.MAX_PAGE_SIZE + 1 - len(books)
        Book.objects.bulk_create(
            Book(author=books[0].author, title=f"b{n}", price=Decimal(1)) for n in range(more)
        )

        served = paging_and_projection.list_books_tool(ada, limit=500)

        assert (len(served["items"]), served["totalPages"]) == (50, 2)

    def test_every_served_row_meets_the_advertised_item(self, ada: Any, books: list[Book]) -> None:
        item = SCHEMA["properties"]["items"]["items"]
        displays = {entry["const"] for entry in item["properties"]["status"]["oneOf"]}

        served = paging_and_projection.list_books_tool(ada)

        for row in served["items"]:
            assert set(row) == set(item["properties"]) == set(item["required"])
            assert row["status"] in displays


@pytest.mark.django_db
class TestTwoMounts:
    def test_the_override_keeps_the_author_as_a_handle(self, ada: Any, books: list[Book]) -> None:
        first = paging_and_projection.books_with_authors_tool(ada)[0]

        assert first == as_stored(WITH_AUTHORS, books[0])

    def test_the_override_is_this_mounts_alone(self) -> None:
        assert paging_and_projection.projection.audience("author_id") is FieldAudience.HIDDEN

    def test_an_override_leaving_two_labels_is_refused_in_the_mounts_name(self) -> None:
        with pytest.raises(ImproperlyConfigured, match=r"^Tool 'by_id': overrides leave"):
            audience_projection_for_spec(
                paging_and_projection.list_books_spec,
                overrides={"id": FieldMarking.label()},
                name="Tool 'by_id'",
            )

    def test_a_caller_naming_no_audience_is_served_every_field(
        self, ada: Any, books: list[Book]
    ) -> None:
        first = paging_and_projection.books_over_http(ada)[0]

        assert first == as_stored(OVER_HTTP, books[0])
