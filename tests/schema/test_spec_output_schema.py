from __future__ import annotations

from typing import Any

import pytest

from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.present import present
from django_service_specs.output.output import Output
from django_service_specs.output.output_field import OutputField
from django_service_specs.output.presenter import Presenter
from django_service_specs.schema.spec_output_schema import spec_output_schema
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from tests.dispatch.utils import OPEN, PK, make_user, note_by_pk, notes_of
from tests.dispatch_app.models import Note


class NoteTitle(Presenter):
    def output(self) -> Output:
        return Output((OutputField("title", "string"),))

    def present(self, value: Any) -> Any:
        return {"title": value.title}


ITEM = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}
NULLABLE_ITEM = {**ITEM, "type": ["object", "null"]}


def write(**_: Any) -> None:
    return None


def nothing(**_: Any) -> Any:
    return Note.objects.none()


def listing(**kwargs: Any) -> SelectorSpec:
    kwargs.setdefault("selector", notes_of)
    return SelectorSpec(kind=SelectorKind.LIST, permissions=OPEN, **kwargs)


def retrieve(**kwargs: Any) -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.RETRIEVE, selector=note_by_pk, reads=PK, permissions=OPEN, **kwargs
    )


class TestSelectorSpecs:
    def test_a_selector_with_no_presenter_has_no_output_schema(self) -> None:
        assert spec_output_schema(listing()) is None

    def test_a_list_presents_an_array_of_items(self) -> None:
        spec = listing(presenter=NoteTitle())

        assert spec_output_schema(spec) == {"type": "array", "items": ITEM}

    def test_a_retrieve_presents_the_item(self) -> None:
        assert spec_output_schema(retrieve(presenter=NoteTitle())) == ITEM

    def test_a_retrieve_allowing_none_admits_null(self) -> None:
        spec = retrieve(presenter=NoteTitle(), allow_none=True)

        assert spec_output_schema(spec) == NULLABLE_ITEM


class TestServiceSpecs:
    def test_a_service_with_no_presenter_anywhere_has_no_output_schema(self) -> None:
        spec = ServiceSpec(
            service=write,
            permissions=OPEN,
            output_selector_spec=listing(selector=nothing),
        )

        assert spec_output_schema(spec) is None

    def test_a_service_presenting_its_own_return_is_the_item(self) -> None:
        spec = ServiceSpec(service=write, permissions=OPEN, presenter=NoteTitle())

        assert spec_output_schema(spec) == ITEM

    def test_a_service_whose_output_selector_is_a_list_presents_an_array(self) -> None:
        reread = listing(selector=nothing, presenter=NoteTitle())
        spec = ServiceSpec(service=write, permissions=OPEN, output_selector_spec=reread)

        assert spec_output_schema(spec) == {"type": "array", "items": ITEM}

    def test_a_service_whose_output_selector_is_a_retrieve_admits_null_without_allow_none(
        self,
    ) -> None:
        reread = SelectorSpec(kind=SelectorKind.RETRIEVE, selector=nothing, presenter=NoteTitle())
        spec = ServiceSpec(service=write, permissions=OPEN, output_selector_spec=reread)

        assert reread.allow_none is False
        assert spec_output_schema(spec) == NULLABLE_ITEM

    def test_the_services_own_presenter_is_shaped_by_its_output_selectors_kind(self) -> None:
        reread = SelectorSpec(kind=SelectorKind.RETRIEVE, selector=nothing)
        spec = ServiceSpec(
            service=write, permissions=OPEN, presenter=NoteTitle(), output_selector_spec=reread
        )

        assert spec_output_schema(spec) == NULLABLE_ITEM


@pytest.mark.django_db
class TestWhatDispatchPresents:
    """Each shape above, against what ``dispatch`` and ``present`` actually return."""

    def test_a_retrieve_allowing_none_presents_null_for_a_missing_row(self) -> None:
        spec = retrieve(presenter=NoteTitle(), allow_none=True)

        result = dispatch(spec, principal=make_user("ada"), arguments={"pk": 404})

        assert present(spec, result) is None
        assert spec_output_schema(spec) == NULLABLE_ITEM

    def test_a_retrieve_without_allow_none_never_presents_a_missing_row(self) -> None:
        spec = retrieve(presenter=NoteTitle())

        result = dispatch(spec, principal=make_user("ada"), arguments={"pk": 404})

        assert result.kind == "not_found"
        with pytest.raises(ValueError, match="nothing to present"):
            present(spec, result)
        assert spec_output_schema(spec) == ITEM

    def test_a_service_whose_reread_finds_nothing_presents_null(self) -> None:
        reread = SelectorSpec(kind=SelectorKind.RETRIEVE, selector=nothing, presenter=NoteTitle())
        spec = ServiceSpec(service=write, permissions=OPEN, output_selector_spec=reread)

        result = dispatch(spec, principal=make_user("ada"), arguments={})

        assert present(spec, result) is None
        assert spec_output_schema(spec) == NULLABLE_ITEM

    def test_a_list_presents_a_list_of_items(self) -> None:
        ada = make_user("ada")
        Note.objects.create(owner=ada, title="Draft")
        spec = listing(presenter=NoteTitle())

        assert present(spec, dispatch(spec, principal=ada, arguments={})) == [{"title": "Draft"}]
        assert spec_output_schema(spec) == {"type": "array", "items": ITEM}
