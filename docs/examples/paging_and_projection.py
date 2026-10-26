"""Serving a long list to an agent: one page at a time, shaped for its reader."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from django.db.models import QuerySet

from django_service_specs import (
    DataclassPresenter,
    FieldMarking,
    Output,
    OutputField,
    Parameter,
    Parameters,
    PresentationContext,
    Presenter,
    SelectorKind,
    SelectorSpec,
    ValueFormatter,
    audience_projection_for_spec,
    dispatch,
    paginate_output,
    present,
    present_for_audience,
    spec_output_schema,
)
from docs.examples.declaring import IsSignedIn
from tests.adapter_app.models import Book, Status

# --8<-- [start:declare]
euros = ValueFormatter(
    lambda amount: f"EUR {amount}",
    produces="string",
    schema={"examples": ["EUR 9.99"]},
)


@dataclass
class BookRow:
    id: Annotated[int, FieldMarking.handle()]
    title: Annotated[str, FieldMarking.label()]
    status: Status
    price: Annotated[Decimal, FieldMarking.formatted(euros)]
    published_on: Annotated[date | None, FieldMarking.timestamp("%d %B %Y")]
    author_id: Annotated[int, FieldMarking.hidden()]


def catalogue(*, user: Any) -> QuerySet[Book]:
    return Book.objects.order_by("pk")


list_books_spec = SelectorSpec(
    kind=SelectorKind.LIST,
    selector=catalogue,
    permissions=[IsSignedIn()],
    presenter=DataclassPresenter(BookRow),
)
# --8<-- [end:declare]


# --8<-- [start:register]
# The transport's own wording and bound, not the spec's.
HANDLE_DESCRIPTION = "An identifier to pass to other tools. Never read it out."
MAX_PAGE_SIZE = 50

# Built once, where the transport registers the spec: the projection a payload
# is shaped by and the schema it is advertised under, from one declaration.
projection = audience_projection_for_spec(list_books_spec, name="Tool 'list_books'")
output_schema = spec_output_schema(
    list_books_spec,
    paginate=True,
    projection=projection,
    handle_description=HANDLE_DESCRIPTION,
)
# --8<-- [end:register]


# --8<-- [start:call]
def list_books_tool(
    user: Any, *, page: int | None = None, limit: int | None = None, **arguments: Any
) -> dict[str, Any]:
    # page and limit are this tool's arguments, not the spec's: they never
    # reach dispatch, whose argument set is closed.
    result = dispatch(list_books_spec, principal=user, arguments=arguments)
    shaped = paginate_output(result.value, page=page, limit=limit, max_page_size=MAX_PAGE_SIZE)
    rows = present_for_audience(
        list_books_spec, replace(result, value=shaped.items), projection=projection
    )
    return shaped.envelope(rows)


# --8<-- [end:call]


# --8<-- [start:override]
# A second mount whose callers do need the author, as a handle to pass on.
with_authors = audience_projection_for_spec(
    list_books_spec,
    overrides={"author_id": FieldMarking.handle()},
    name="Tool 'books_with_authors'",
)


def books_with_authors_tool(user: Any) -> Any:
    result = dispatch(list_books_spec, principal=user, arguments={})
    return present_for_audience(list_books_spec, result, projection=with_authors)


# --8<-- [end:override]


# --8<-- [start:unprojected]
def books_over_http(user: Any) -> Any:
    # A caller naming no audience is presented every field, unprojected.
    return present(list_books_spec, dispatch(list_books_spec, principal=user, arguments={}))


# --8<-- [end:unprojected]


# --8<-- [start:shapes]
class ChosenFields(Presenter):
    """Each book with its handle and the fields the caller chose, or every field."""

    def output(self) -> Output:
        return Output(
            (
                OutputField("id", "integer"),
                # Left out of a row whose caller did not choose them. The
                # schema of a spec declaring shapes requires no field of a row
                # anyway, since a selection can leave out any of them.
                OutputField("title", "string", always_present=False),
                OutputField("price", "string", always_present=False),
            )
        )

    def present(self, value: Book) -> dict[str, Any]:
        return {"id": value.pk, "title": value.title, "price": str(value.price)}

    def presented(self, value: Book, context: PresentationContext | None) -> dict[str, Any]:
        row = self.present(value)
        chosen = context.shapes.get("fields") if context is not None else None
        if chosen is None:  # not sent: every field
            return row
        return {name: row[name] for name in ("id", *chosen)}


pick_books_spec = SelectorSpec(
    kind=SelectorKind.LIST,
    selector=catalogue,  # never handed "fields"
    permissions=[IsSignedIn()],
    presenter=ChosenFields(),
    shapes=Parameters.of(
        Parameter(
            "fields",
            "array",
            items="string",
            choices=["title", "price"],
            required=False,
            json_schema_extra={"uniqueItems": True},
        )
    ),
)
# --8<-- [end:shapes]
