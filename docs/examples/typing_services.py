"""Typing a service: a Protocol stated with ``implements``, checked by a type checker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db.models import QuerySet

from django_service_specs import (
    CreateService,
    DataclassValidator,
    DeleteService,
    NoInput,
    Parameter,
    Parameters,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    implements,
)
from docs.examples.declaring import IsSignedIn
from tests.dispatch_app.models import Note


def own_note(*, user: Any, pk: int) -> QuerySet[Note]:
    return Note.objects.filter(owner=user, pk=pk)


the_note = SelectorSpec(
    kind=SelectorKind.RETRIEVE,
    selector=own_note,
    reads=Parameters.of(Parameter("pk", "integer", required=True)),
)


# --8<-- [start:typed]
@dataclass
class NoteIn:
    title: str


@implements(CreateService[NoteIn, Note])
def create_note(*, data: NoteIn, **extras: Any) -> Note:
    return Note.objects.create(owner=extras["user"], title=data.title)


@implements(DeleteService[NoInput, Note, None])  # reads no input, so no `data`
def delete_note(*, instance: Note, **extras: Any) -> None:
    instance.delete()


create_note_spec = ServiceSpec(
    service=create_note, permissions=[IsSignedIn()], validator=DataclassValidator(NoteIn)
)
delete_note_spec = ServiceSpec(
    service=delete_note, permissions=[IsSignedIn()], instance_selector_spec=the_note
)
# --8<-- [end:typed]
