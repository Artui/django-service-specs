"""The async entry point: only the run may be ``async def``."""

from __future__ import annotations

# --8<-- [start:async]
from typing import Any

from django_service_specs import ServiceSpec, adispatch, apresent
from docs.examples.quickstart import IsOwner, rename_note_spec
from tests.dispatch_app.models import Note


async def rename_note_async(*, instance: Note, title: str) -> Note:
    instance.title = title
    await instance.asave(update_fields=["title"])
    return instance


# The same declaration as the sync quickstart, with an async run. The permission
# check, the selector and the Validator stay sync: adispatch runs them in one
# executor hop, and runs this service inside the transaction ``atomic`` opens.
arename_note_spec = ServiceSpec(
    service=rename_note_async,
    permissions=[IsOwner()],
    validator=rename_note_spec.validator,
    instance_selector_spec=rename_note_spec.instance_selector_spec,
    presenter=rename_note_spec.presenter,
)


async def rename_from_a_worker(user_id: Any, arguments: dict[str, Any]) -> Any:
    # A queue carries an identifier, not a user: adispatch resolves it, and a
    # missing or deactivated user is refused with PrincipalUnavailable.
    result = await adispatch(arename_note_spec, principal_id=user_id, arguments=arguments)
    if result.kind == "not_found":
        return None
    return await apresent(arename_note_spec, result)


# --8<-- [end:async]
