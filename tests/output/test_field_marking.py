from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model

from django_service_specs.http.spec_view import SpecView
from django_service_specs.output.field_audience import FieldAudience
from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.output.output import Output
from django_service_specs.output.output_field import OutputField
from django_service_specs.output.presenter import Presenter
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from tests.dispatch.utils import OPEN, notes_of
from tests.dispatch_app.models import Note
from tests.http.utils import FACTORY, body, signed_in


class MarkedNote(Presenter):
    """A handle, a label, and plumbing an agent audience is not shown."""

    def output(self) -> Output:
        return Output(
            (
                OutputField("id", "integer", marking=FieldMarking.handle()),
                OutputField("title", "string", marking=FieldMarking.label()),
                OutputField("owner_id", "integer", marking=FieldMarking.hidden()),
            )
        )

    def present(self, value: Any) -> Any:
        return {"id": value.pk, "title": value.title, "owner_id": value.owner_id}


def test_constructors_name_the_audience() -> None:
    assert FieldMarking() == FieldMarking(FieldAudience.CONTENT, None)
    assert FieldMarking.handle("opaque") == FieldMarking(FieldAudience.HANDLE, "opaque")
    assert FieldMarking.hidden() == FieldMarking(FieldAudience.HIDDEN)
    assert FieldMarking.label() == FieldMarking(FieldAudience.LABEL)


def test_audience_is_a_json_friendly_string() -> None:
    assert FieldAudience.HANDLE == "handle"


@pytest.mark.django_db
def test_a_caller_naming_no_audience_is_presented_every_field() -> None:
    """Every HTTP response is such a caller: a hidden field is still served."""
    ada = get_user_model().objects.create_user(username="ada")
    note = Note.objects.create(owner=ada, title="Draft")
    spec = SelectorSpec(
        kind=SelectorKind.LIST, selector=notes_of, permissions=OPEN, presenter=MarkedNote()
    )

    response = SpecView.as_view(spec=spec)(signed_in(FACTORY.get("/"), ada))

    assert body(response) == [{"id": note.pk, "title": "Draft", "owner_id": ada.pk}]
