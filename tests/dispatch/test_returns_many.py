"""``returns_many``: a service's own return dispatched and presented as a list, row by row.

The field is the output half of ``many``, so these cases dispatch a spec
taking one set of arguments and read back what ``present`` and its async and
audience siblings hand a transport. Each asserts the result's kind before it
presents, so a tree that ignores the field fails at that assertion rather
than inside the presenter, handed a list where it expects a row.
"""

from __future__ import annotations

from typing import Any

import pytest
from asgiref.sync import sync_to_async

from django_service_specs.dispatch.adispatch import adispatch
from django_service_specs.dispatch.apresent import apresent
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.present import present
from django_service_specs.dispatch.present_for_audience import present_for_audience
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.specs.service_spec import ServiceSpec
from tests.dispatch.utils import OPEN, Record, Titles, make_user
from tests.dispatch_app.models import Note
from tests.output.utils import PROJECTED_ROW, ROW, InvoicePresenter

pytestmark = pytest.mark.django_db(transaction=True)

OWNER = Parameters.of(Parameter("owner", "string", required=True))


def returning(rows: Any, presenter: Any) -> tuple[ServiceSpec, Record]:
    """A spec whose service takes one argument and returns ``rows``, with the service to read back."""
    service = Record(returns=rows)
    spec = ServiceSpec(
        service=service, permissions=OPEN, reads=OWNER, presenter=presenter, returns_many=True
    )
    return spec, service


def notes() -> list[Note]:
    ada = make_user("ada")
    return [Note.objects.create(owner=ada, title=title) for title in ("First", "Second")]


def test_a_list_of_rows_is_presented_row_by_row() -> None:
    rows = notes()
    presenter = Titles()
    spec, service = returning(rows, presenter)

    result = dispatch(spec, principal=rows[0].owner, arguments={"owner": "ada"})

    assert result.kind == "list"
    assert present(spec, result) == [{"title": "First"}, {"title": "Second"}]
    # Each row reached the item presenter on its own, never the list.
    assert presenter.seen == rows
    # The input is left alone: one call, with the one argument as declared.
    assert [call["owner"] for call in service.calls] == ["ada"]


def test_a_list_of_mappings_is_presented_row_by_row() -> None:
    ada = make_user("ada")
    spec, _ = returning([ROW, {**ROW, "id": 8}], InvoicePresenter())

    result = dispatch(spec, principal=ada, arguments={"owner": "ada"})

    assert result.kind == "list"
    assert present(spec, result) == [ROW, {**ROW, "id": 8}]


def test_an_empty_list_is_presented_as_one() -> None:
    # Not ``None``: no rows is still a list, and ``present`` hands back ``[]``.
    ada = make_user("ada")
    spec, _ = returning([], Titles())

    result = dispatch(spec, principal=ada, arguments={"owner": "ada"})

    assert result.kind == "list"
    assert present(spec, result) == []


def test_a_none_return_presents_none() -> None:
    # One value, as a ``many`` service's ``None`` is: as a list it would be
    # refused by ``present`` after the service had run.
    ada = make_user("ada")
    spec, _ = returning(None, Titles())

    result = dispatch(spec, principal=ada, arguments={"owner": "ada"})

    assert result.kind == "instance"
    assert present(spec, result) is None


def test_without_the_field_a_returned_list_is_one_value() -> None:
    # The other half of the cases above: the field is what makes the list, so
    # the same return from a spec without it reaches the presenter whole.
    ada = make_user("ada")
    spec = ServiceSpec(service=Record(returns=[ROW]), permissions=OPEN, reads=OWNER)

    result = dispatch(spec, principal=ada, arguments={"owner": "ada"})

    assert result.kind == "instance"
    assert present(spec, result) == [ROW]


def test_each_row_is_projected_for_an_audience() -> None:
    ada = make_user("ada")
    spec, _ = returning([ROW, ROW], InvoicePresenter())

    result = dispatch(spec, principal=ada, arguments={"owner": "ada"})

    assert result.kind == "list"
    assert present_for_audience(spec, result) == [PROJECTED_ROW, PROJECTED_ROW]


async def test_the_async_path_presents_row_by_row() -> None:
    rows = await sync_to_async(notes)()
    spec, _ = returning(rows, Titles())

    result = await adispatch(spec, principal=rows[0].owner, arguments={"owner": "ada"})

    assert result.kind == "list"
    assert await apresent(spec, result) == [{"title": "First"}, {"title": "Second"}]


async def test_the_async_path_presents_a_none_return_as_none() -> None:
    ada = await sync_to_async(make_user)("ada")
    spec, _ = returning(None, Titles())

    result = await adispatch(spec, principal=ada, arguments={"owner": "ada"})

    assert result.kind == "instance"
    assert await apresent(spec, result) is None
