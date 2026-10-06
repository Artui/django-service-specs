from __future__ import annotations

from typing import Any

import pytest

from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.present import present
from django_service_specs.output.audience_projection_for_spec import audience_projection_for_spec
from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.output.output import Output
from django_service_specs.output.output_field import OutputField
from django_service_specs.output.presenter import Presenter
from django_service_specs.schema.output_schema import output_schema
from django_service_specs.schema.spec_output_schema import spec_output_schema
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from tests.dispatch.utils import (
    BOOKS_OPEN,
    EDIT,
    OPEN,
    PK,
    RENAME,
    make_user,
    note_by_pk,
    notes_of,
)
from tests.dispatch_app.models import Note
from tests.output.utils import HANDLE_DESCRIPTION, INVOICE, PROJECTED_SCHEMA, InvoicePresenter


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
        """Undeclared, a ``None`` is not stated: the item stays strict."""
        spec = ServiceSpec(service=write, permissions=OPEN, presenter=NoteTitle())

        assert spec.allow_none is False
        assert spec_output_schema(spec) == ITEM

    def test_a_service_allowing_none_admits_null(self) -> None:
        spec = ServiceSpec(service=write, permissions=OPEN, presenter=NoteTitle(), allow_none=True)

        assert spec_output_schema(spec) == NULLABLE_ITEM

    def test_allow_none_changes_nothing_beside_a_retrieve_reread(self) -> None:
        """The re-read already admits null, declared or not."""
        reread = SelectorSpec(kind=SelectorKind.RETRIEVE, selector=nothing, presenter=NoteTitle())

        for allow_none in (False, True):
            spec = ServiceSpec(
                service=write,
                permissions=OPEN,
                output_selector_spec=reread,
                allow_none=allow_none,
            )
            assert spec_output_schema(spec) == NULLABLE_ITEM

    def test_allow_none_changes_nothing_beside_a_list_reread(self) -> None:
        """The re-read's rows are what is presented, never the service's ``None``."""
        reread = listing(selector=nothing, presenter=NoteTitle())
        spec = ServiceSpec(
            service=write, permissions=OPEN, output_selector_spec=reread, allow_none=True
        )

        assert spec_output_schema(spec) == {"type": "array", "items": ITEM}

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

    @pytest.mark.parametrize("allow_none", [False, True])
    def test_a_service_that_returns_nothing_presents_null(self, allow_none: bool) -> None:
        """Presented as ``None`` either way; only a declared ``allow_none`` says so,
        because whether a service may return nothing is not otherwise in its
        declaration."""
        spec = ServiceSpec(
            service=write, permissions=OPEN, presenter=NoteTitle(), allow_none=allow_none
        )

        result = dispatch(spec, principal=make_user("ada"), arguments={})

        assert present(spec, result) is None
        assert spec_output_schema(spec) == (NULLABLE_ITEM if allow_none else ITEM)

    def test_a_list_presents_a_list_of_items(self) -> None:
        ada = make_user("ada")
        Note.objects.create(owner=ada, title="Draft")
        spec = listing(presenter=NoteTitle())

        assert present(spec, dispatch(spec, principal=ada, arguments={})) == [{"title": "Draft"}]
        assert spec_output_schema(spec) == {"type": "array", "items": ITEM}


# Generated by running the published DRF-based ``output_to_json_schema`` over a
# serializer declaring the same one ``title`` field, ``kind=LIST, paginate=True``:
# its item is ``ITEM`` exactly, so the envelope around it is the one to match.
PAGED = {
    "type": "object",
    "properties": {
        "items": {"type": "array", "items": ITEM},
        "page": {"type": "integer"},
        "totalPages": {"type": "integer"},
        "hasNext": {"type": "boolean"},
    },
    "required": ["items", "page", "totalPages", "hasNext"],
}


class TestPaging:
    def test_a_list_is_a_bare_array_unless_paging_is_asked_for(self) -> None:
        assert spec_output_schema(listing(presenter=NoteTitle())) == {
            "type": "array",
            "items": ITEM,
        }

    def test_a_paged_list_is_the_envelope_around_the_array(self) -> None:
        assert spec_output_schema(listing(presenter=NoteTitle()), paginate=True) == PAGED

    def test_a_service_whose_output_selector_is_a_list_is_paged_the_same_way(self) -> None:
        reread = listing(selector=nothing, presenter=NoteTitle())
        spec = ServiceSpec(service=write, permissions=OPEN, output_selector_spec=reread)

        assert spec_output_schema(spec, paginate=True) == PAGED

    @pytest.mark.parametrize(
        ("spec", "expected"),
        [
            pytest.param(retrieve(presenter=NoteTitle()), ITEM, id="retrieve"),
            pytest.param(
                retrieve(presenter=NoteTitle(), allow_none=True), NULLABLE_ITEM, id="allow-none"
            ),
            pytest.param(
                ServiceSpec(service=write, permissions=OPEN, presenter=NoteTitle()),
                ITEM,
                id="service-return",
            ),
        ],
    )
    def test_paging_changes_nothing_that_is_not_a_list(
        self, spec: ServiceSpec | SelectorSpec, expected: dict[str, Any]
    ) -> None:
        """One row has no pages: the flag describes how a list is served, and
        a transport may pass it for every spec it lists."""
        assert spec_output_schema(spec, paginate=True) == expected

    def test_a_spec_with_no_output_is_still_none_when_paged(self) -> None:
        assert spec_output_schema(listing(), paginate=True) is None


class TestProjection:
    """The schema of what ``present_for_audience`` hands back, for a caller naming an audience."""

    def test_a_caller_naming_no_audience_is_described_in_full(self) -> None:
        schema = spec_output_schema(retrieve(presenter=InvoicePresenter()))

        assert schema == output_schema(INVOICE)
        assert "etag" in schema["properties"]

    def test_the_projection_lands_on_the_item(self) -> None:
        spec = retrieve(presenter=InvoicePresenter())

        schema = spec_output_schema(
            spec,
            projection=audience_projection_for_spec(spec),
            handle_description=HANDLE_DESCRIPTION,
        )

        assert schema == PROJECTED_SCHEMA

    def test_the_handle_wording_defaults_to_none(self) -> None:
        spec = retrieve(presenter=InvoicePresenter())

        schema = spec_output_schema(spec, projection=audience_projection_for_spec(spec))

        assert schema["properties"]["id"] == {"type": "integer"}

    def test_the_projection_lands_on_a_lists_items(self) -> None:
        spec = listing(presenter=InvoicePresenter())

        schema = spec_output_schema(
            spec,
            projection=audience_projection_for_spec(spec),
            handle_description=HANDLE_DESCRIPTION,
        )

        assert schema == {"type": "array", "items": PROJECTED_SCHEMA}

    def test_the_projection_lands_on_a_pages_items_and_never_on_the_envelope(self) -> None:
        """The envelope's keys belong to no ``Output``: a mount hiding a field
        that happens to be called ``page`` hides it from the rows alone."""
        spec = listing(presenter=InvoicePresenter())
        projection = audience_projection_for_spec(spec, overrides={"page": FieldMarking.hidden()})

        schema = spec_output_schema(
            spec, paginate=True, projection=projection, handle_description=HANDLE_DESCRIPTION
        )

        assert schema == {
            **PAGED,
            "properties": {
                **PAGED["properties"],
                "items": {"type": "array", "items": PROJECTED_SCHEMA},
            },
        }

    def test_a_projected_item_that_may_be_none_admits_null(self) -> None:
        spec = retrieve(presenter=InvoicePresenter(), allow_none=True)

        schema = spec_output_schema(
            spec,
            projection=audience_projection_for_spec(spec),
            handle_description=HANDLE_DESCRIPTION,
        )

        assert schema == {**PROJECTED_SCHEMA, "type": ["object", "null"]}

    def test_a_service_presenting_its_own_return_is_projected_as_the_item(self) -> None:
        spec = ServiceSpec(service=write, permissions=OPEN, presenter=InvoicePresenter())

        schema = spec_output_schema(
            spec,
            projection=audience_projection_for_spec(spec),
            handle_description=HANDLE_DESCRIPTION,
        )

        assert schema == PROJECTED_SCHEMA


ANSWERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "rename": {
            "type": "object",
            "properties": {
                "available": {"type": "boolean"},
                "code": {"type": "string", "enum": ["note_archived", "books_closed"]},
                "reason": {"type": "string"},
            },
            "required": ["available"],
        },
        "edit": {
            "type": "object",
            "properties": {"available": {"type": "boolean"}},
            "required": ["available"],
        },
    },
    "required": ["rename", "edit"],
}


def answered(item: dict[str, Any]) -> dict[str, Any]:
    """``item`` declaring the ``affordances`` object every presented row then carries."""
    return {
        **item,
        "properties": {**item["properties"], "affordances": ANSWERS},
        "required": [*item["required"], "affordances"],
    }


AFFORDANCES = {"rename": RENAME, "edit": EDIT}


class TestAffordances:
    """The ``affordances`` object a selector spec's declaration adds to each presented row."""

    def test_a_list_s_items_declare_the_answers(self) -> None:
        spec = listing(presenter=NoteTitle(), affordances=AFFORDANCES)

        assert spec_output_schema(spec) == {"type": "array", "items": answered(ITEM)}

    def test_a_page_s_items_declare_them_and_the_envelope_does_not(self) -> None:
        spec = listing(presenter=NoteTitle(), affordances=AFFORDANCES)

        assert spec_output_schema(spec, paginate=True) == {
            **PAGED,
            "properties": {
                **PAGED["properties"],
                "items": {"type": "array", "items": answered(ITEM)},
            },
        }

    def test_a_retrieve_allowing_none_declares_them_on_the_item_that_admits_null(self) -> None:
        spec = retrieve(presenter=NoteTitle(), allow_none=True, affordances=AFFORDANCES)

        assert spec_output_schema(spec) == {**answered(ITEM), "type": ["object", "null"]}

    def test_a_projected_item_declares_the_same_answers_reason_included(self) -> None:
        # After the projection, which walks declared fields and has nothing to
        # say about a key no Output declares; an agent reads the reason too.
        spec = retrieve(presenter=InvoicePresenter(), affordances=AFFORDANCES)

        schema = spec_output_schema(
            spec,
            projection=audience_projection_for_spec(spec),
            handle_description=HANDLE_DESCRIPTION,
        )

        assert schema == answered(PROJECTED_SCHEMA)

    def test_a_service_spec_declares_its_output_selector_s_answers_not_its_own(self) -> None:
        spec = ServiceSpec(
            service=write,
            permissions=OPEN,
            affordances=[BOOKS_OPEN],
            output_selector_spec=SelectorSpec(
                kind=SelectorKind.RETRIEVE,
                selector=note_by_pk,
                presenter=NoteTitle(),
                affordances={"edit": EDIT},
            ),
        )
        own_only = ServiceSpec(
            service=write, permissions=OPEN, presenter=NoteTitle(), affordances=[BOOKS_OPEN]
        )

        schema = spec_output_schema(spec)

        assert schema is not None
        assert schema["properties"]["affordances"] == {
            "type": "object",
            "properties": {"edit": ANSWERS["properties"]["edit"]},
            "required": ["edit"],
        }
        assert spec_output_schema(own_only) == ITEM

    @pytest.mark.django_db
    def test_every_presented_row_has_what_its_schema_requires_and_nothing_else(self) -> None:
        ada = make_user("ada")
        Note.objects.create(owner=ada, title="live")
        Note.objects.create(owner=ada, title="archived", archived=True)
        spec = listing(presenter=NoteTitle(), affordances=AFFORDANCES)
        item = answered(ITEM)

        rows = present(spec, dispatch(spec, principal=ada, arguments={}))

        for row in rows:
            assert sorted(row) == sorted(item["required"])
            for name, answer in row["affordances"].items():
                declared = ANSWERS["properties"][name]
                assert set(declared["required"]) <= set(answer) <= set(declared["properties"])
                assert answer.get("code", "note_archived") in ["note_archived", "books_closed"]
        assert rows[1]["affordances"]["rename"]["code"] == "note_archived"
