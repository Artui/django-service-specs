from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db.models import QuerySet

from django_service_specs import UNSET, UnsetType, is_supplied, supplied_fields
from tests.dispatch_app.models import Note


# --8<-- [start:supplied]
@dataclass
class NoteQuery:  # every filter may be left out, and then holds UNSET
    title: str | UnsetType = UNSET
    archived: bool | UnsetType = UNSET


def matching_notes(*, user: Any, query: NoteQuery) -> QuerySet[Note]:
    # Only the filters the caller sent: one left out filters nothing.
    return Note.objects.filter(owner=user, **supplied_fields(query))


def heading(query: NoteQuery) -> str:
    if is_supplied(query.title):
        return query.title.upper()  # narrowed to ``str``
    return "All notes"


# --8<-- [end:supplied]
