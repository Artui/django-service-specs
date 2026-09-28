from __future__ import annotations

from typing import Any

import pytest

from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.present import present
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from tests.dispatch.utils import OPEN, Record, Titles, make_user, notes_of
from tests.dispatch_app.models import Note

LIST = SelectorKind.LIST
RETRIEVE = SelectorKind.RETRIEVE


class Row:
    def __init__(self, title: str) -> None:
        self.title = title


def selector_spec(kind: SelectorKind = RETRIEVE, presenter: Any = None) -> SelectorSpec:
    return SelectorSpec(kind=kind, selector=notes_of, permissions=OPEN, presenter=presenter)


def test_an_instance_goes_through_the_selector_spec_s_presenter() -> None:
    presenter = Titles()

    rendered = present(selector_spec(presenter=presenter), DispatchResult("instance", Row("a")))

    assert rendered == {"title": "a"}


def test_a_list_is_presented_item_by_item() -> None:
    presenter = Titles()
    rows = (Row("a"), Row("b"))

    rendered = present(selector_spec(LIST, presenter), DispatchResult("list", rows))

    assert rendered == [{"title": "a"}, {"title": "b"}]
    assert presenter.seen == list(rows)


def test_an_instance_with_no_presenter_is_returned_as_it_is() -> None:
    row = Row("a")

    assert present(selector_spec(), DispatchResult("instance", row)) is row


@pytest.mark.django_db
def test_a_list_with_no_presenter_is_evaluated_into_a_list() -> None:
    # A queryset handed back lazily would run its query wherever the caller
    # first iterates it, which for ``apresent``'s caller is the event loop.
    note = Note.objects.create(owner=make_user("ada"), title="a")

    rendered = present(selector_spec(LIST), DispatchResult("list", Note.objects.all()))

    assert rendered == [note]
    assert type(rendered) is list


def test_a_none_value_is_not_handed_to_the_presenter() -> None:
    presenter = Titles()

    assert present(selector_spec(presenter=presenter), DispatchResult("instance", None)) is None
    assert presenter.seen == []


def test_a_service_spec_presents_through_its_own_presenter() -> None:
    spec = ServiceSpec(service=Record(), permissions=OPEN, presenter=Titles())

    assert present(spec, DispatchResult("instance", Row("a"))) == {"title": "a"}


def test_a_service_spec_with_none_uses_its_output_selector_s() -> None:
    spec = ServiceSpec(
        service=Record(),
        permissions=OPEN,
        output_selector_spec=SelectorSpec(kind=LIST, selector=notes_of, presenter=Titles()),
    )

    assert present(spec, DispatchResult("list", [Row("a")])) == [{"title": "a"}]


def test_a_service_spec_with_no_presenter_anywhere_returns_its_value() -> None:
    spec = ServiceSpec(service=Record(), permissions=OPEN)

    assert present(spec, DispatchResult("instance", "done")) == "done"


@pytest.mark.parametrize("presenter", [None, Titles()], ids=["no presenter", "presenter"])
def test_not_found_has_nothing_to_present(presenter: Any) -> None:
    with pytest.raises(ValueError) as caught:
        present(selector_spec(presenter=presenter), DispatchResult("not_found"))

    assert str(caught.value) == (
        "A not-found result has nothing to present. Answer it as the transport's own "
        "not-found before presenting."
    )
