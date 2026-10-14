"""``UpdateService``: the keywords it names are the ones dispatch hands a service."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.services.implements import implements
from django_service_specs.services.update_service import UpdateService
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
from tests.dispatch.utils import OPEN, PK, Titled, make_user, note_by_pk
from tests.dispatch_app.models import Note


@pytest.mark.django_db
def test_a_conforming_service_receives_the_resolved_row_and_the_validated_input() -> None:
    note = Note.objects.create(owner=make_user("ada"), title="Draft")

    @implements(UpdateService[Mapping[str, Any], Note, Note])
    def rename_note(*, instance: Note, data: Mapping[str, Any], **extras: Any) -> Note:
        instance.title = data["title"]
        instance.save()
        return instance

    spec = ServiceSpec(
        service=rename_note,
        permissions=OPEN,
        validator=Titled(),
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE, selector=note_by_pk, reads=PK
        ),
    )

    result = dispatch(spec, principal=note.owner, arguments={"pk": note.pk, "title": "Final"})

    assert result.value == note
    note.refresh_from_db()
    assert note.title == "Final"
