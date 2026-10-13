"""Declaring writes: many rows in one call, and a provider filling a server-owned field."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

from django_service_specs import (
    DataclassValidator,
    Parameter,
    Parameters,
    ServiceSpec,
)
from docs.examples.declaring import IsSignedIn
from tests.dispatch_app.models import Note


# --8<-- [start:many]
@dataclass
class NoteIn:  # one row
    title: str


def add_notes(*, user: Any, data: list[NoteIn], archived: bool = False) -> list[Note]:
    return [Note.objects.create(owner=user, title=row.title, archived=archived) for row in data]


add_notes_spec = ServiceSpec(
    service=add_notes,
    permissions=[IsSignedIn()],
    validator=DataclassValidator(NoteIn),  # what each row is
    many=True,  # the rows travel under "items"
    many_min_length=1,  # an empty list is refused rather than run on no rows
    many_max_length=200,  # and so is one past 200, before any row is read
    reads=Parameters.of(Parameter("archived", "boolean")),  # asked once, beside the list
)
# --8<-- [end:many]


# --8<-- [start:providers]
class Owned(TypedDict):  # the keys the provider fills, readable before it runs
    owner_id: int


def the_owner(*, user: Any) -> Owned:
    return {"owner_id": user.pk}


@dataclass
class NoteCreate:
    title: str
    owner_id: int


def create_note(*, data: NoteCreate) -> Note:
    return Note.objects.create(title=data.title, owner_id=data.owner_id)


create_note_spec = ServiceSpec(
    service=create_note,
    permissions=[IsSignedIn()],
    validator=DataclassValidator(NoteCreate),
    # Merged over the caller's arguments before the Validator sees them, so
    # the owner is the signed-in user whatever the caller sends.
    input_data=the_owner,
)
# server_owned_keys(create_note_spec) names "owner_id": a transport's schema
# need not ask for it, and dispatch does not demand it of the caller.
# --8<-- [end:providers]
