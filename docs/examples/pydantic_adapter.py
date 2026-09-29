"""The pydantic adapter: a nested write declared as models, its names, and a tree."""

from __future__ import annotations

# --8<-- [start:write]
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, Field, model_validator

from django_service_specs import (
    ChangeResult,
    ChildSpec,
    FieldMarking,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    create_from_input,
)
from django_service_specs.adapters.pydantic import PydanticPresenter, PydanticValidator
from docs.examples.declaring import IsSignedIn
from tests.adapter_app.models import Author, Book, Status


class BookIn(BaseModel):
    title: str = Field(max_length=100)
    price: Decimal = Field(gt=0, description="In euros.")
    status: Status = Status.DRAFT
    published_on: date | None = None
    # The key a relation write matches an incoming row by.
    pk: int | None = None

    @model_validator(mode="after")
    def _dated_when_published(self) -> BookIn:
        if self.status == Status.PUBLISHED and self.published_on is None:
            raise ValueError("A published book has a publication date.")
        return self


class AuthorIn(BaseModel):
    name: str
    books: list[BookIn] = Field(default_factory=list)


class BookOut(BaseModel):
    id: Annotated[int, FieldMarking.handle()]
    title: Annotated[str, FieldMarking.label()]
    price: Decimal
    status: Status


class AuthorOut(BaseModel):
    id: Annotated[int, FieldMarking.handle()]
    name: str
    books: list[BookOut]


def create_author(*, data: dict[str, Any]) -> ChangeResult[Author]:
    return create_from_input(Author, data, relations={"books": ChildSpec(model=Book, fk="author")})


create_author_spec = ServiceSpec(
    service=create_author,
    permissions=[IsSignedIn()],
    validator=PydanticValidator(AuthorIn),
    output_selector_spec=SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda *, result: Author.objects.filter(pk=result.instance.pk),
        prefetch_related=["books"],
        presenter=PydanticPresenter(AuthorOut),
    ),
)
# --8<-- [end:write]


# --8<-- [start:names]
class Contact(BaseModel):
    # Validated from "fullName" and dumped as "fullName".
    full_name: str = Field(alias="fullName")
    # Validated from "mail" and dumped as "email".
    email: str = Field(validation_alias="mail", serialization_alias="email")


contact_validator = PydanticValidator(Contact)
contact_presenter = PydanticPresenter(Contact)
# --8<-- [end:names]


# --8<-- [start:tree]
class Category(BaseModel):
    name: str
    children: list[Category] = []


category_validator = PydanticValidator(Category)
# --8<-- [end:tree]
