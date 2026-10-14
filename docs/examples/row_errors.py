"""A refusal class from a library the kernel cannot name, re-rooted under the row that raised it."""

from __future__ import annotations

from typing import Any

# --8<-- [start:register]
from django_service_specs import ChildSpec, create_from_input, register_row_error
from tests.adapter_app.models import Author, Book


class CatalogueRefusal(Exception):
    """A validation error from another library, which a row service written for it raises."""

    def __init__(self, detail: Any) -> None:
        super().__init__(detail)
        self.detail = detail


def read_refusal(exc: CatalogueRefusal) -> Any:
    return exc.detail


def ready() -> None:  # an AppConfig.ready(), or the adapter's own import
    register_row_error(CatalogueRefusal, read_refusal)


def create_book(*, data: dict[str, Any]) -> Book:
    if data["title"].isupper():
        raise CatalogueRefusal({"title": ["No titles in capitals."]})
    return Book.objects.create(**data)


def create_author(*, data: dict[str, Any]) -> Author:
    books = {"books": ChildSpec(model=Book, fk="author", create_service=create_book)}
    return create_from_input(Author, data, relations=books).instance


# --8<-- [end:register]
