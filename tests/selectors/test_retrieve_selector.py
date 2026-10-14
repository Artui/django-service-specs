"""``RetrieveSelector``: one row or ``None``, the lookup the spec reads through ``**extras``."""

from __future__ import annotations

from typing import Any

import pytest

from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.selectors.retrieve_selector import RetrieveSelector
from django_service_specs.services.implements import implements
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from tests.dispatch.utils import OPEN, PK, make_user
from tests.dispatch_app.models import Note


@implements(RetrieveSelector[Note])
def note_or_none(**extras: Any) -> Note | None:
    return Note.objects.filter(pk=extras["pk"]).first()


def _spec(**kwargs: Any) -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.RETRIEVE, selector=note_or_none, reads=PK, permissions=OPEN, **kwargs
    )


@pytest.mark.django_db
def test_the_lookup_the_spec_reads_arrives_through_extras() -> None:
    note = Note.objects.create(owner=make_user("ada"), title="Minutes")

    result = dispatch(_spec(), principal=note.owner, arguments={"pk": note.pk})

    assert result.value == note


@pytest.mark.django_db
def test_none_is_not_found_unless_the_spec_allows_it() -> None:
    ada = make_user("ada")

    assert dispatch(_spec(), principal=ada, arguments={"pk": 404}).kind == "not_found"
    allowed = dispatch(_spec(allow_none=True), principal=ada, arguments={"pk": 404})
    assert allowed.kind == "instance"
    assert allowed.value is None
