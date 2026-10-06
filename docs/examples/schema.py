"""JSON Schema from a spec's declarations: what it takes, and what it returns."""

from __future__ import annotations

from typing import Any

# --8<-- [start:schema]
from django_service_specs import (
    DataclassPresenter,
    ServiceSpec,
    UnknownArguments,
    spec_input_schema,
    spec_output_schema,
)
from docs.examples.declaring import IsSignedIn, NoteRow, list_notes_spec
from docs.examples.relations import create_author_spec
from tests.dispatch_app.models import Note

# What a transport advertises for the notes list: its arguments, and its rows.
notes_input = spec_input_schema(list_notes_spec)
notes_output = spec_output_schema(list_notes_spec)

# The author write, as a transport that refuses an undeclared argument...
author_input = spec_input_schema(create_author_spec)
# ...and as one that drops it, which must not claim to refuse it.
lenient_author_input = spec_input_schema(
    create_author_spec, unknown_arguments=UnknownArguments.IGNORE
)
author_output = spec_output_schema(create_author_spec)
# --8<-- [end:schema]


# --8<-- [start:allow_none]
def archive_oldest(*, user: Any) -> Note | None:
    note = Note.objects.filter(owner=user, archived=False).order_by("pk").first()
    if note is not None:
        note.archived = True
        note.save(update_fields=["archived"])
    return note  # None once there is nothing left to archive


archive_oldest_spec = ServiceSpec(
    service=archive_oldest,
    permissions=[IsSignedIn()],
    presenter=DataclassPresenter(NoteRow),
    # It presents what it returned, which may be nothing: said here, so the
    # schema a transport advertises admits the null it will serve.
    allow_none=True,
)
archive_output = spec_output_schema(archive_oldest_spec)
# --8<-- [end:allow_none]
