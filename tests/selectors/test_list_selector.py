"""``ListSelector``: a ``LIST`` selector returning its rows, every keyword through ``**extras``."""

from __future__ import annotations

from typing import Any

import pytest
from django.db.models import QuerySet

from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.selectors.list_selector import ListSelector
from django_service_specs.services.implements import implements
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.types.selector_kind import SelectorKind
from tests.dispatch.utils import OPEN, make_user
from tests.dispatch_app.models import Note


@implements(ListSelector[Note])
def notes_of_the_caller(**extras: Any) -> QuerySet[Note]:
    return Note.objects.filter(owner=extras["user"])


@pytest.mark.django_db
def test_a_conforming_selector_receives_the_pool_and_its_rows_are_the_result() -> None:
    ada, bob = make_user("ada"), make_user("bob")
    mine = Note.objects.create(owner=ada, title="Mine")
    Note.objects.create(owner=bob, title="Theirs")
    spec = SelectorSpec(kind=SelectorKind.LIST, selector=notes_of_the_caller, permissions=OPEN)

    result = dispatch(spec, principal=ada, arguments={})

    assert list(result.value) == [mine]
