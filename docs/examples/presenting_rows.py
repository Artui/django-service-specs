"""A Presenter that batches one lookup over every row it presents."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from django.db.models import Count, QuerySet

from django_service_specs import (
    Output,
    OutputField,
    PresentationContext,
    Presenter,
    SelectorKind,
    SelectorSpec,
    dispatch,
    paginate_output,
    present,
)
from docs.examples.declaring import IsSignedIn
from tests.adapter_app.models import Book, Edition


# --8<-- [start:batching]
class BooksWithEditions(Presenter):
    """Each book with its number of editions, counted once for every row presented."""

    def output(self) -> Output:
        return Output(
            (
                OutputField("id", "integer"),
                OutputField("title", "string"),
                OutputField("editions", "integer"),
            )
        )

    def present(self, value: Book) -> dict[str, Any]:
        # One book alone, as a retrieve presents it, is a batch of one.
        return self.presented_rows((value,), None)[0]

    def presented_rows(
        self, values: Sequence[Book], context: PresentationContext | None
    ) -> list[dict[str, Any]]:
        counts = dict(
            Edition.objects.filter(book__in=values)
            .order_by()
            .values_list("book")
            .annotate(Count("pk"))
        )
        # One presented value per row, in the order the rows were given.
        return [
            {"id": book.pk, "title": book.title, "editions": counts.get(book.pk, 0)}
            for book in values
        ]


def catalogue(*, user: Any) -> QuerySet[Book]:
    return Book.objects.order_by("title")


books_spec = SelectorSpec(
    kind=SelectorKind.LIST,
    selector=catalogue,
    permissions=[IsSignedIn()],
    presenter=BooksWithEditions(),
)
# --8<-- [end:batching]


# --8<-- [start:page]
def first_page(user: Any, limit: int) -> list[dict[str, Any]]:
    result = dispatch(books_spec, principal=user, arguments={})
    page = paginate_output(result.value, limit=limit)
    # presented_rows is handed the page's rows, never the whole catalogue.
    return present(books_spec, replace(result, value=page.items))


# --8<-- [end:page]
