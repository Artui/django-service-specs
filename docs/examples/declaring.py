"""Declaring operations: a read with its own Parameters, and a write's dataclasses."""

from __future__ import annotations

# --8<-- [start:selector]
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from django.db.models import QuerySet

from django_service_specs import (
    UNSET,
    DataclassPresenter,
    DataclassValidator,
    FieldMarking,
    Parameter,
    Parameters,
    PermissionCheck,
    SelectorKind,
    SelectorSpec,
    UnsetType,
)
from tests.adapter_app.models import Status
from tests.dispatch_app.models import Note


class IsSignedIn(PermissionCheck):
    def has_permission(self, principal: Any, spec: Any) -> bool:
        return principal.is_authenticated


@dataclass
class NoteRow:
    id: Annotated[int, FieldMarking.handle()]
    title: Annotated[str, FieldMarking.label()]


def notes_of(*, user: Any, search: str = "", ordering: str = "title") -> QuerySet[Note]:
    return Note.objects.filter(owner=user, title__icontains=search).order_by(ordering)


list_notes_spec = SelectorSpec(
    kind=SelectorKind.LIST,
    selector=notes_of,
    permissions=[IsSignedIn()],
    reads=Parameters.of(
        Parameter("search", "string", help="Part of the title, in any case."),
        Parameter("ordering", "string", choices=["title", "-title"], default="title"),
    ),
    select_related=["owner"],
    presenter=DataclassPresenter(NoteRow),
)
# --8<-- [end:selector]


# --8<-- [start:validator]
@dataclass
class BookIn:
    title: str
    price: Decimal
    status: Status = Status.DRAFT
    published_on: date | None = None
    pk: int | None = None  # present for a row that exists, absent for a new one


@dataclass
class AuthorIn:
    name: str
    books: list[BookIn] = field(default_factory=list)


@dataclass
class AuthorPatch:  # every field may be left out, and then holds UNSET
    name: str | UnsetType = UNSET
    books: list[BookIn] | UnsetType = UNSET


# A spec takes a Validator instance: the adapter, wrapping the declaration.
author_validator = DataclassValidator(AuthorIn)
# --8<-- [end:validator]
