"""Affordances: what can be done right now, declared once on the operation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from django.conf import settings
from django.db.models import Q

from django_service_specs import (
    DEFAULT_POOL_SEEDS,
    AdditionalInputRequired,
    Affordance,
    DataclassPresenter,
    DataclassValidator,
    ServiceSpec,
    authorize,
    authorize_target,
    base_pool,
    bind_arguments,
    dispatch,
    enforce_affordances,
    resolve_callable_kwargs,
    unmet_operation_affordance,
)
from docs.examples.declaring import IsSignedIn, list_notes_spec
from docs.examples.quickstart import IsOwner, NoteOut, Rename, rename_note, rename_note_spec
from tests.dispatch_app.models import Note

# --8<-- [start:declare]
# An ambient fact a condition may read, registered like any other pool seed.
seeds = DEFAULT_POOL_SEEDS.extend(
    read_only=lambda: getattr(settings, "NOTES_READ_ONLY", False),
)

rename_spec = ServiceSpec(
    service=rename_note,
    permissions=[IsOwner()],
    validator=DataclassValidator(Rename),
    instance_selector_spec=rename_note_spec.instance_selector_spec,
    presenter=DataclassPresenter(NoteOut),
    affordances=[
        Affordance(  # a condition on nothing in particular: a callable over the seeds
            code="notes_read_only",
            reason="Notes are read-only during maintenance.",
            when=lambda *, read_only: not read_only,
        ),
        Affordance(  # a condition on the row: an ORM expression, answered in SQL
            code="note_archived",
            reason="An archived note cannot be renamed. Restore it first.",
            when=Q(archived=False),
        ),
    ],
    idempotent=True,  # renaming twice to one title leaves what renaming once did
)
# --8<-- [end:declare]


# --8<-- [start:offer]
OPERATIONS = {"list_notes": list_notes_spec, "rename_note": rename_spec}


def tools_for(user: Any) -> dict[str, str | None]:
    """Each operation a transport could offer, with the code of what withholds it."""
    pool = base_pool(user=user, seeds=seeds)  # the seeds a call would be handed
    tools: dict[str, str | None] = {}
    for name, spec in OPERATIONS.items():
        unmet = unmet_operation_affordance(spec, pool, reserved=seeds.reserved)
        tools[name] = None if unmet is None else unmet.code
    return tools


# --8<-- [end:offer]


# --8<-- [start:enforce]
def rename_step(user: Any, note: Note, title: str) -> Note:
    """One step of a chain that resolved its row itself and runs the service in hand."""
    grant = authorize(rename_spec, user)
    authorize_target(rename_spec, user, note, grant=grant)
    data = bind_arguments(rename_spec, {"pk": note.pk, "title": title}, principal=user, target=note)
    pool = base_pool(user=user, seeds=seeds)
    pool.update({**data, "data": data, "instance": note})  # the pool the service receives
    enforce_affordances(rename_spec, pool, instance=note, reserved=seeds.reserved)
    return rename_spec.service(**resolve_callable_kwargs(rename_spec.service, pool))


# --8<-- [end:enforce]


# --8<-- [start:confirm]
@dataclass
class Purge:
    confirmed: bool = False  # declared, so the second call may send it


def purge_archived(*, user: Any, confirmed: bool) -> int:
    doomed = Note.objects.filter(owner=user, archived=True)
    count = doomed.count()
    if count > 1 and not confirmed:
        raise AdditionalInputRequired(
            f"{count} archived notes will be deleted. Confirm to proceed.",
            schema={"confirmed": {"type": "boolean"}},
        )
    doomed.delete()
    return count


purge_spec = ServiceSpec(
    service=purge_archived,
    permissions=[IsSignedIn()],
    validator=DataclassValidator(Purge),
)


def purge(user: Any, arguments: dict[str, Any]) -> int:
    return dispatch(purge_spec, principal=user, arguments=arguments).value


# --8<-- [end:confirm]


# --8<-- [start:selector]
# The list, declaring which operations' answers its rows are asked for.
list_notes_with_answers_spec = replace(list_notes_spec, affordances={"rename": rename_spec})
# --8<-- [end:selector]
