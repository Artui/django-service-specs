"""``DeleteService``: the keywords it names are the ones dispatch hands a service."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.services.delete_service import DeleteService
from django_service_specs.services.implements import implements
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.no_input import NoInput
from tests.dispatch.utils import OPEN, PK, Titled, make_user, note_by_pk
from tests.dispatch_app.models import Note

TARGET = SelectorSpec(kind=SelectorKind.RETRIEVE, selector=note_by_pk, reads=PK)


@pytest.mark.django_db
def test_a_service_reading_no_input_leaves_data_out_and_receives_the_row() -> None:
    note = Note.objects.create(owner=make_user("ada"), title="Draft")

    @implements(DeleteService[NoInput, Note, None])
    def delete_note(*, instance: Note, **extras: Any) -> None:
        instance.delete()

    spec = ServiceSpec(service=delete_note, permissions=OPEN, instance_selector_spec=TARGET)

    dispatch(spec, principal=note.owner, arguments={"pk": note.pk})

    assert not Note.objects.filter(pk=note.pk).exists()


@pytest.mark.django_db
def test_a_service_taking_input_declares_data_and_receives_it() -> None:
    note = Note.objects.create(owner=make_user("ada"), title="Draft")
    reasons: list[str] = []

    @implements(DeleteService[Mapping[str, Any], Note, None])
    def delete_note(
        *, instance: Note, data: Mapping[str, Any] | None = None, **extras: Any
    ) -> None:
        assert data is not None
        reasons.append(data["title"])
        instance.delete()

    spec = ServiceSpec(
        service=delete_note, permissions=OPEN, validator=Titled(), instance_selector_spec=TARGET
    )

    dispatch(spec, principal=note.owner, arguments={"pk": note.pk, "title": "Duplicate"})

    assert reasons == ["Duplicate"]
    assert not Note.objects.filter(pk=note.pk).exists()
