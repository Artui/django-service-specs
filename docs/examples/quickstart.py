"""The quickstart: one write, declared once, dispatched and presented.

``README.md`` carries the section between the markers verbatim, and
``tests/docs/test_examples.py`` holds the two to each other.
"""

from __future__ import annotations

# --8<-- [start:quickstart]
from dataclasses import dataclass
from typing import Any

from django_service_specs import (
    DataclassPresenter,
    DataclassValidator,
    Parameter,
    Parameters,
    PermissionCheck,
    SelectorKind,
    SelectorSpec,
    ServiceSpec,
    dispatch,
    present,
)
from tests.dispatch_app.models import Note  # a title, and an owner who is a user


@dataclass
class Rename:  # what the operation takes
    title: str


@dataclass
class NoteOut:  # what it returns
    id: int
    title: str


class IsOwner(PermissionCheck):
    message = "Only the note's owner may rename it."

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return principal.is_authenticated

    def has_object_permission(self, principal: Any, spec: Any, target: Any) -> bool:
        return target.owner_id == principal.pk


def rename_note(*, instance: Note, title: str) -> Note:
    instance.title = title
    instance.save(update_fields=["title"])
    return instance


rename_note_spec = ServiceSpec(
    service=rename_note,
    permissions=[IsOwner()],
    validator=DataclassValidator(Rename),
    instance_selector_spec=SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda *, pk: Note.objects.filter(pk=pk),  # the row, or none
        reads=Parameters.of(Parameter("pk", "integer", required=True)),
    ),
    presenter=DataclassPresenter(NoteOut),
)


def rename(user: Any, arguments: dict[str, Any]) -> Any:
    result = dispatch(rename_note_spec, principal=user, arguments=arguments)
    if result.kind == "not_found":
        return None  # a transport answers this in its own terms: a 404, an exit code
    return present(rename_note_spec, result)


# --8<-- [end:quickstart]
