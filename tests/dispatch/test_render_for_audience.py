from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from asgiref.sync import sync_to_async

from django_service_specs.dispatch.apresent import apresent
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.paginate_output import paginate_output
from django_service_specs.dispatch.present import present
from django_service_specs.dispatch.render_for_audience import render_for_audience
from django_service_specs.output.audience_projection import AudienceProjection
from django_service_specs.output.audience_projection_for_spec import audience_projection_for_spec
from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.output.output import Output
from django_service_specs.output.output_field import OutputField
from django_service_specs.output.presenter import Presenter
from django_service_specs.output.project_payload import project_payload
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from tests.dispatch.utils import OPEN, make_user, notes_of
from tests.dispatch_app.models import Note
from tests.output.utils import PROJECTED_ROW, ROW, InvoicePresenter


class NoteRow(Presenter):
    """A handle, a label, and plumbing an agent must not see."""

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


def spec_of(presenter: Presenter | None, kind: SelectorKind = SelectorKind.LIST) -> SelectorSpec:
    return SelectorSpec(kind=kind, selector=notes_of, permissions=OPEN, presenter=presenter)


def test_derives_the_projection_from_the_spec_when_given_none() -> None:
    spec = spec_of(InvoicePresenter(), SelectorKind.RETRIEVE)

    assert render_for_audience(spec, DispatchResult("instance", ROW)) == PROJECTED_ROW


def test_projects_each_row_of_a_list() -> None:
    spec = spec_of(InvoicePresenter())

    rendered = render_for_audience(spec, DispatchResult("list", [ROW, ROW]))

    assert rendered == [PROJECTED_ROW, PROJECTED_ROW]


def test_uses_a_projection_built_once_and_passed_in() -> None:
    """A transport builds the projection where it registers the spec, with a
    mount's overrides, and the render applies exactly that one."""
    spec = spec_of(InvoicePresenter(), SelectorKind.RETRIEVE)
    projection = audience_projection_for_spec(spec, overrides={"etag": FieldMarking()})

    rendered = render_for_audience(spec, DispatchResult("instance", ROW), projection=projection)

    assert rendered == {**PROJECTED_ROW, "etag": "W/1"}


def test_an_empty_projection_is_presenting_and_nothing_else() -> None:
    spec = spec_of(InvoicePresenter(), SelectorKind.RETRIEVE)
    result = DispatchResult("instance", ROW)

    rendered = render_for_audience(spec, result, projection=AudienceProjection())

    assert rendered == present(spec, result) == ROW


def test_a_spec_with_no_presenter_passes_the_value_through() -> None:
    assert render_for_audience(spec_of(None), DispatchResult("list", [{"a": 1}])) == [{"a": 1}]


def test_nothing_found_is_still_nothing_to_present() -> None:
    with pytest.raises(ValueError, match="nothing to present"):
        render_for_audience(spec_of(InvoicePresenter()), DispatchResult("not_found"))


@pytest.mark.django_db
class TestFromDispatch:
    def test_a_dispatched_list_is_presented_and_projected(self) -> None:
        ada = make_user("ada")
        note = Note.objects.create(owner=ada, title="Draft")
        spec = spec_of(NoteRow())

        result = dispatch(spec, principal=ada, arguments={})

        assert render_for_audience(spec, result) == [{"id": note.pk, "title": "Draft"}]
        # The same result, presented for a caller naming no audience, is whole.
        assert present(spec, result) == [{"id": note.pk, "title": "Draft", "owner_id": ada.pk}]

    def test_one_page_is_presented_projected_and_wrapped(self) -> None:
        ada = make_user("ada")
        Note.objects.bulk_create([Note(owner=ada, title=f"n{index}") for index in range(5)])
        spec = spec_of(NoteRow())

        result = dispatch(spec, principal=ada, arguments={})
        page = paginate_output(result.value, page=2, limit=2)
        rendered = render_for_audience(spec, replace(result, value=page.items))

        assert page.envelope(rendered) == {
            "items": [{"id": n.pk, "title": n.title} for n in Note.objects.all()[2:4]],
            "page": 2,
            "totalPages": 3,
            "hasNext": True,
        }


@pytest.mark.django_db(transaction=True)
async def test_from_async_code_the_presented_value_is_projected_on_the_loop() -> None:
    """Presenting a lazy queryset on the loop would raise; projecting what
    ``apresent`` brought back reads no row, so it needs no hop of its own."""
    ada = await sync_to_async(make_user)("ada")
    note = await Note.objects.acreate(owner=ada, title="Draft")
    spec = spec_of(NoteRow())
    projection = audience_projection_for_spec(spec)

    rendered = project_payload(
        await apresent(spec, DispatchResult("list", Note.objects.all())), projection
    )

    assert rendered == [{"id": note.pk, "title": "Draft"}]
