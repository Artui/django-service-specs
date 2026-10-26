from __future__ import annotations

from typing import Any

import pytest

from django_service_specs.affordances.utils import AFFORDANCES_KEY
from django_service_specs.dispatch.audience_projection_for_spec import audience_projection_for_spec
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.present import present
from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.output.output import Output, OutputField
from django_service_specs.output.presentation_context import PresentationContext
from django_service_specs.output.presenter import Presenter
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.schema.output_schema import output_schema
from django_service_specs.schema.spec_output_schema import spec_output_schema
from django_service_specs.schema.utils import allow_null
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
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
from tests.schema.utils import NoteTitle, nothing, walk, write
from tests.specs.utils import Foreign, Titled

ITEM = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}
NULLABLE_ITEM = {**ITEM, "type": ["object", "null"]}
ARRAY = {"type": "array", "items": ITEM}


def listing(**kwargs: Any) -> SelectorSpec:
    kwargs.setdefault("selector", notes_of)
    return SelectorSpec(kind=SelectorKind.LIST, permissions=OPEN, **kwargs)


def retrieve(**kwargs: Any) -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.RETRIEVE, selector=note_by_pk, reads=PK, permissions=OPEN, **kwargs
    )


def service(**kwargs: Any) -> ServiceSpec:
    return ServiceSpec(service=write, permissions=OPEN, **kwargs)


def retrieve_re_read(**kwargs: Any) -> SelectorSpec:
    return SelectorSpec(kind=SelectorKind.RETRIEVE, selector=nothing, **kwargs)


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        pytest.param(listing(), None, id="a-selector-with-no-presenter-has-no-output-schema"),
        # A bare array unless paging is asked for: TestPaging is the other half.
        pytest.param(listing(presenter=NoteTitle()), ARRAY, id="a-list-presents-an-array-of-items"),
        pytest.param(retrieve(presenter=NoteTitle()), ITEM, id="a-retrieve-presents-the-item"),
        pytest.param(
            retrieve(presenter=NoteTitle(), allow_none=True),
            NULLABLE_ITEM,
            id="a-retrieve-allowing-none-admits-null",
        ),
        # Its selector's ``None`` is presented as the empty list, so ``"null"``
        # is never stated.
        pytest.param(
            listing(selector=nothing, presenter=NoteTitle(), allow_none=True),
            ARRAY,
            id="a-list-selector-allowing-none-is-an-array-never-null",
        ),
        pytest.param(
            service(output_selector_spec=listing(selector=nothing)),
            None,
            id="a-service-with-no-presenter-anywhere-has-no-output-schema",
        ),
        pytest.param(
            service(presenter=NoteTitle(), many=True, validator=Titled()),
            ARRAY,
            id="a-many-service-presents-an-array-of-its-item",
        ),
        pytest.param(
            service(presenter=NoteTitle(), many=True, validator=Titled(), allow_none=True),
            allow_null(ARRAY),
            id="a-many-service-allowing-none-admits-null-for-the-whole-array",
        ),
        pytest.param(
            service(presenter=NoteTitle(), allow_none=True),
            NULLABLE_ITEM,
            id="a-service-allowing-none-admits-null",
        ),
        # The re-read already admits null, declared or not; undeclared is
        # test_a_service_whose_output_selector_is_a_retrieve_admits_null_without_allow_none.
        pytest.param(
            service(output_selector_spec=retrieve_re_read(presenter=NoteTitle()), allow_none=True),
            NULLABLE_ITEM,
            id="allow-none-changes-nothing-beside-a-retrieve-re-read",
        ),
        # The re-read's rows are what is presented, never the service's ``None``.
        pytest.param(
            service(
                output_selector_spec=listing(selector=nothing, presenter=NoteTitle()),
                allow_none=True,
            ),
            ARRAY,
            id="allow-none-changes-nothing-beside-a-list-re-read",
        ),
        pytest.param(
            service(output_selector_spec=listing(selector=nothing, presenter=NoteTitle())),
            ARRAY,
            id="a-service-whose-output-selector-is-a-list-presents-an-array",
        ),
        pytest.param(
            service(presenter=NoteTitle(), output_selector_spec=retrieve_re_read()),
            NULLABLE_ITEM,
            id="the-services-own-presenter-is-shaped-by-its-output-selectors-kind",
        ),
    ],
)
def test_the_shape_around_the_item(spec: Any, expected: dict[str, Any] | None) -> None:
    assert spec_output_schema(spec) == expected


def test_a_service_presenting_its_own_return_is_the_item() -> None:
    """Undeclared, a ``None`` is not stated: the item stays strict."""
    spec = service(presenter=NoteTitle())

    assert spec.allow_none is False
    assert spec_output_schema(spec) == ITEM


def test_a_service_whose_output_selector_is_a_retrieve_admits_null_without_allow_none() -> None:
    reread = retrieve_re_read(presenter=NoteTitle())
    spec = service(output_selector_spec=reread)

    assert reread.allow_none is False
    assert spec_output_schema(spec) == NULLABLE_ITEM


class TestReturnsMany:
    """A service declaring ``returns_many`` presents its own return as an array of the item.

    Built inside each test rather than in ``test_the_shape_around_the_item``'s
    table, so a tree without the field fails each case on its own rather than
    the module's collection.
    """

    @pytest.mark.parametrize("paginate", [False, True], ids=["bare", "paginate-asked"])
    @pytest.mark.parametrize(
        ("allow_none", "expected"),
        [
            pytest.param(False, ARRAY, id="strict"),
            # The ``many`` service's rule: a ``None`` return is presented as
            # ``None``, so ``"null"`` wraps the whole array.
            pytest.param(True, allow_null(ARRAY), id="allowing-none-admits-null-for-the-array"),
        ],
    )
    def test_an_array_of_the_item_never_paged(
        self, allow_none: bool, expected: dict[str, Any], paginate: bool
    ) -> None:
        # Never paged: dispatch hands back every row the service returned, so
        # there is no page to describe, whatever a transport asks for.
        spec = service(presenter=NoteTitle(), returns_many=True, allow_none=allow_none)

        assert spec_output_schema(spec, paginate=paginate) == expected

    def test_a_projection_lands_on_the_array_s_items(self) -> None:
        spec = service(presenter=InvoicePresenter(), returns_many=True)

        schema = spec_output_schema(
            spec,
            projection=audience_projection_for_spec(spec),
            handle_description=HANDLE_DESCRIPTION,
        )

        assert schema == {"type": "array", "items": PROJECTED_SCHEMA}


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
        reread = retrieve_re_read(presenter=NoteTitle())
        spec = service(output_selector_spec=reread)

        result = dispatch(spec, principal=make_user("ada"), arguments={})

        assert present(spec, result) is None
        assert spec_output_schema(spec) == NULLABLE_ITEM

    @pytest.mark.parametrize("allow_none", [False, True])
    def test_a_service_that_returns_nothing_presents_null(self, allow_none: bool) -> None:
        """Presented as ``None`` either way; only a declared ``allow_none`` says so,
        because whether a service may return nothing is not otherwise in its
        declaration."""
        spec = service(presenter=NoteTitle(), allow_none=allow_none)

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
    def test_a_paged_list_is_the_envelope_around_the_array(self) -> None:
        assert spec_output_schema(listing(presenter=NoteTitle()), paginate=True) == PAGED

    def test_a_service_whose_output_selector_is_a_list_is_paged_the_same_way(self) -> None:
        reread = listing(selector=nothing, presenter=NoteTitle())
        spec = service(output_selector_spec=reread)

        assert spec_output_schema(spec, paginate=True) == PAGED

    @pytest.mark.parametrize(
        ("spec", "expected"),
        [
            pytest.param(retrieve(presenter=NoteTitle()), ITEM, id="retrieve"),
            pytest.param(
                retrieve(presenter=NoteTitle(), allow_none=True), NULLABLE_ITEM, id="allow-none"
            ),
            pytest.param(
                service(presenter=NoteTitle()),
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


def projected(spec: ServiceSpec | SelectorSpec) -> dict[str, Any] | None:
    """``spec``'s output schema for an audience, with the handle wording a transport passes."""
    return spec_output_schema(
        spec, projection=audience_projection_for_spec(spec), handle_description=HANDLE_DESCRIPTION
    )


class TestProjection:
    """The schema of what ``present_for_audience`` hands back, for a caller naming an audience."""

    def test_a_caller_naming_no_audience_is_described_in_full(self) -> None:
        schema = spec_output_schema(retrieve(presenter=InvoicePresenter()))

        assert schema == output_schema(INVOICE)
        assert "etag" in schema["properties"]

    def test_the_projection_lands_on_the_item(self) -> None:
        spec = retrieve(presenter=InvoicePresenter())

        schema = projected(spec)

        assert schema == PROJECTED_SCHEMA

    def test_the_handle_wording_defaults_to_none(self) -> None:
        spec = retrieve(presenter=InvoicePresenter())

        schema = spec_output_schema(spec, projection=audience_projection_for_spec(spec))

        assert schema["properties"]["id"] == {"type": "integer"}

    def test_the_projection_lands_on_a_lists_items(self) -> None:
        spec = listing(presenter=InvoicePresenter())

        schema = projected(spec)

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

        schema = projected(spec)

        assert schema == {**PROJECTED_SCHEMA, "type": ["object", "null"]}

    def test_a_service_presenting_its_own_return_is_projected_as_the_item(self) -> None:
        spec = service(presenter=InvoicePresenter())

        schema = projected(spec)

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

        schema = projected(spec)

        assert schema == answered(PROJECTED_SCHEMA)

    def test_a_service_spec_declares_its_output_selector_s_answers_not_its_own(self) -> None:
        spec = service(
            affordances=[BOOKS_OPEN],
            output_selector_spec=SelectorSpec(
                kind=SelectorKind.RETRIEVE,
                selector=note_by_pk,
                presenter=NoteTitle(),
                affordances={"edit": EDIT},
            ),
        )
        own_only = service(presenter=NoteTitle(), affordances=[BOOKS_OPEN])

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


class TestSources:
    @pytest.mark.parametrize(
        "compiled",
        [
            pytest.param(listing(presenter=NoteTitle()), id="list"),
            pytest.param(retrieve(presenter=NoteTitle(), allow_none=True), id="retrieve"),
            pytest.param(
                service(
                    output_selector_spec=retrieve(presenter=NoteTitle()),
                ),
                id="re-read",
            ),
        ],
    )
    def test_a_source_is_described_as_the_spec_it_compiles_to(self, compiled: Any) -> None:
        assert spec_output_schema(Foreign(compiled)) == spec_output_schema(compiled)
        assert spec_output_schema(Foreign(compiled)) is not None


class Card(Presenter):
    """A row with a nested object, a nullable one and an array of objects, each requiring a key."""

    def output(self) -> Output:
        named = Output((OutputField("name", "string"),))
        return Output(
            (
                OutputField("title", "string"),
                OutputField("author", "object", fields=named),
                OutputField("editor", "object", fields=named, nullable=True),
                OutputField("tags", "array", items=Output((OutputField("label", "string"),))),
            )
        )

    def present(self, value: Any) -> Any:
        return {"title": value.title}


class Chosen(Presenter):
    """``NoteTitle``, leaving ``title`` out unless the call's ``fields`` shape names it."""

    def output(self) -> Output:
        return NoteTitle().output()

    def present(self, value: Any) -> Any:
        return {"title": value.title}

    def presented(self, value: Any, context: PresentationContext | None) -> Any:
        chosen = context.shapes.get("fields") if context is not None else None
        row = self.present(value)
        return row if chosen is None else {key: row[key] for key in chosen}


FIELDS = Parameters.of(Parameter("fields", "array", items="string", required=False))


def requirements(schema: dict[str, Any]) -> list[list[str]]:
    """Every ``required`` list in ``schema``, at any depth."""
    return [node["required"] for node in walk(schema) if "required" in node]


def item_of(schema: dict[str, Any]) -> dict[str, Any]:
    """The item inside ``schema``: a page's array's ``items``, an array's ``items``, or itself."""
    if "page" in schema.get("properties", {}):
        return schema["properties"]["items"]["items"]
    if schema.get("type") in ("array", ["array", "null"]):
        return schema["items"]
    return schema


class TestShapes:
    """A spec declaring ``shapes`` promises no field of a row, at any depth.

    A shape reaches the presenter alone, and a ``fields`` selection there
    leaves keys out, so no field the presenter declares can be promised.
    """

    @pytest.mark.parametrize(
        ("spec", "paginate"),
        [
            pytest.param(retrieve(presenter=Card(), shapes=FIELDS), False, id="the-item-itself"),
            pytest.param(
                retrieve(presenter=Card(), shapes=FIELDS, allow_none=True),
                False,
                id="an-item-admitting-null",
            ),
            pytest.param(listing(presenter=Card(), shapes=FIELDS), False, id="an-arrays-items"),
            pytest.param(listing(presenter=Card(), shapes=FIELDS), True, id="a-pages-items"),
            pytest.param(service(presenter=Card(), shapes=FIELDS), False, id="a-services-return"),
            pytest.param(
                service(presenter=Card(), shapes=FIELDS, many=True, validator=Titled()),
                False,
                id="a-many-services-items",
            ),
            pytest.param(
                service(presenter=Card(), shapes=FIELDS, returns_many=True, allow_none=True),
                False,
                id="a-returns-many-array-admitting-null",
            ),
            pytest.param(
                service(
                    shapes=FIELDS, output_selector_spec=listing(selector=nothing, presenter=Card())
                ),
                True,
                id="a-services-paged-re-read",
            ),
        ],
    )
    def test_every_shaped_item_requires_nothing_wherever_it_sits(
        self, spec: Any, paginate: bool
    ) -> None:
        schema = spec_output_schema(spec, paginate=paginate)
        assert schema is not None

        item = item_of(schema)
        assert requirements(item) == []
        # Every field is still described, nested ones included: only the
        # promise is gone.
        assert set(item["properties"]) == {"title", "author", "editor", "tags"}
        assert item["properties"]["editor"]["type"] == ["object", "null"]
        assert set(item["properties"]["editor"]["properties"]) == {"name"}
        assert set(item["properties"]["tags"]["items"]["properties"]) == {"label"}

    def test_the_envelope_around_a_shaped_page_keeps_its_own(self) -> None:
        schema = spec_output_schema(listing(presenter=Card(), shapes=FIELDS), paginate=True)
        assert schema is not None

        assert requirements(schema) == [["items", "page", "totalPages", "hasNext"]]

    @pytest.mark.parametrize("paginate", [False, True], ids=["array", "page"])
    def test_a_shaped_row_keeps_the_affordances_dispatch_adds_required(
        self, paginate: bool
    ) -> None:
        spec = listing(presenter=NoteTitle(), shapes=FIELDS, affordances=AFFORDANCES)
        schema = spec_output_schema(spec, paginate=paginate)
        assert schema is not None

        item = item_of(schema)
        assert item["required"] == [AFFORDANCES_KEY]
        # The answers' own schema is the kernel's, whole.
        assert item["properties"][AFFORDANCES_KEY] == ANSWERS
        assert item["properties"]["title"] == {"type": "string"}

    def test_a_shaped_projected_item_is_projected_and_requires_nothing(self) -> None:
        schema = projected(retrieve(presenter=InvoicePresenter(), shapes=FIELDS))
        assert schema is not None

        assert requirements(schema) == []
        assert set(schema["properties"]) == set(PROJECTED_SCHEMA["properties"])
        assert schema["properties"]["number"] == PROJECTED_SCHEMA["properties"]["number"]

    @pytest.mark.parametrize(
        "spec",
        [
            pytest.param(retrieve(presenter=Card()), id="retrieve"),
            pytest.param(listing(presenter=Card()), id="list"),
            pytest.param(service(presenter=Card()), id="service-return"),
        ],
    )
    def test_a_spec_declaring_no_shapes_keeps_every_required(self, spec: Any) -> None:
        schema = spec_output_schema(spec)
        assert schema is not None

        assert item_of(schema) == output_schema(Card().output())
        assert requirements(item_of(schema)) == [
            ["title", "author", "editor", "tags"],
            ["name"],
            ["name"],
            ["label"],
        ]

    @pytest.mark.django_db
    def test_a_row_a_selection_shortens_still_has_all_its_schema_requires(self) -> None:
        ada = make_user("ada")
        Note.objects.create(owner=ada, title="live")
        spec = listing(presenter=Chosen(), shapes=FIELDS, affordances=AFFORDANCES)
        schema = spec_output_schema(spec)
        assert schema is not None
        assert "title" in schema["items"]["properties"]

        rows = present(spec, dispatch(spec, principal=ada, arguments={"fields": []}))

        assert "title" not in rows[0]
        assert set(schema["items"]["required"]) <= set(rows[0])
