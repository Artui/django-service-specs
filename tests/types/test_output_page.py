from __future__ import annotations

import dataclasses

import pytest

from django_service_specs.types.output_page import OutputPage


def test_the_envelope_is_the_shape_the_paged_schema_states() -> None:
    page = OutputPage(items=[1, 2], page=2, limit=100, total=250)

    assert page.envelope(["rendered"]) == {
        "items": ["rendered"],
        "page": 2,
        "totalPages": 3,
        "hasNext": True,
    }


def test_the_envelope_carries_the_rendered_rows_and_not_the_slice() -> None:
    """The projection lands on the rows; the envelope's own keys belong to no
    declaration, so the caller presents the slice and hands the result back."""
    page = OutputPage(items=["a row"], page=1, limit=2, total=1)

    assert page.envelope([{"id": 1}])["items"] == [{"id": 1}]


def test_no_rows_is_one_page_and_not_zero() -> None:
    page = OutputPage(items=[], page=1, limit=10, total=0)

    assert (page.total_pages, page.has_next) == (1, False)


@pytest.mark.parametrize(
    ("page_number", "has_next"),
    [(1, True), (2, True), (3, False)],
)
def test_there_is_a_next_page_until_the_last(page_number: int, has_next: bool) -> None:
    page = OutputPage(items=[], page=page_number, limit=100, total=201)

    assert page.total_pages == 3
    assert page.has_next is has_next


def test_a_page_is_frozen() -> None:
    page = OutputPage(items=[], page=1, limit=10, total=0)

    with pytest.raises(dataclasses.FrozenInstanceError):
        page.page = 2  # type: ignore[misc]
