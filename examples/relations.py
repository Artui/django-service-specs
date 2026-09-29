"""A nested write: an author and its books, created and then reconciled."""

from __future__ import annotations

# --8<-- [start:write]
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django_service_specs import (
    ChangeResult,
    ChildSpec,
    DataclassPresenter,
    DataclassValidator,
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    create_from_input,
    update_from_input,
)
from docs.examples.declaring import AuthorIn, AuthorPatch, IsSignedIn
from tests.adapter_app.models import Author, Book, Status

# One declaration of how the books are written, shared by the create and the update.
BOOKS = {"books": ChildSpec(model=Book, fk="author")}


@dataclass
class BookOut:
    id: int
    title: str
    price: Decimal
    status: Status


@dataclass
class AuthorOut:
    id: int
    name: str
    books: list[BookOut]


def create_author(*, data: dict[str, Any]) -> ChangeResult[Author]:
    return create_from_input(Author, data, relations=BOOKS)


def update_author(*, instance: Author, data: dict[str, Any]) -> ChangeResult[Author]:
    return update_from_input(instance, data, relations=BOOKS)


# The services return what changed; the output selector re-reads the author,
# with its books prefetched, for the presenter.
reread_author = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=lambda *, result: Author.objects.filter(pk=result.instance.pk),
    prefetch_related=["books"],
    presenter=DataclassPresenter(AuthorOut),
)

create_author_spec = ServiceSpec(
    service=create_author,
    permissions=[IsSignedIn()],
    validator=DataclassValidator(AuthorIn),
    output_selector_spec=reread_author,
)

update_author_spec = ServiceSpec(
    service=update_author,
    permissions=[IsSignedIn()],
    validator=DataclassValidator(AuthorPatch),
    instance_selector_spec=SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda *, pk: Author.objects.filter(pk=pk),
        reads=Parameters.of(Parameter("pk", "integer", required=True)),
    ),
    output_selector_spec=reread_author,
)
# --8<-- [end:write]
