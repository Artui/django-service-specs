"""A collection's row error has the tree ``InvalidArguments`` documents.

A caller validating rows and writing them through ``relations=`` receives both
refusals from one dispatch, so the two have to agree on how a failing row is
addressed: keyed by its ``int`` index, only the rows that failed, and a message
about the row itself under ``non_field_errors`` inside it. There is one form,
whatever transport reads it; offering another is an adapter's business.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from django_service_specs.mutations.acreate_from_input import acreate_from_input
from django_service_specs.mutations.create_from_input import create_from_input
from django_service_specs.mutations.nested_writes import _RowPath
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.relations.child_spec import ChildSpec
from django_service_specs.relations.many_to_many_spec import ManyToManySpec
from tests.parameters.utils import coded
from tests.relations_app.models import Catalog, Post, Section, Tag

_RUDE: dict[str, Any] = {"title": ["Too rude."]}
_ROWS: list[dict[str, Any]] = [{"title": "ok"}, {"title": "rude"}, {"title": "fine"}]


def _refuses_the_rude_row(*, data: dict[str, Any]) -> Section:
    if data["title"] == "rude":
        raise InvalidArguments(_RUDE)
    return Section.objects.create(**data)


@pytest.mark.django_db
class TestTheTreeIsTheKernelsOwn:
    def _refused(self) -> dict[Any, Any]:
        with pytest.raises(InvalidArguments) as excinfo:
            create_from_input(
                Catalog,
                {"name": "c", "sections": _ROWS},
                relations={
                    "sections": ChildSpec(
                        model=Section, fk="catalog", create_service=_refuses_the_rude_row
                    )
                },
            )
        return excinfo.value.detail

    def test_the_failing_row_alone_is_keyed_by_its_int_index(self) -> None:
        detail = self._refused()

        assert detail == {"sections": {1: _RUDE}}
        # An ``int``, not the string ``"1"``: the tree is addressed by the
        # position in the arguments, and only serializing it writes a string.
        [key] = detail["sections"]
        assert type(key) is int

    def test_the_tree_serializes_once_its_keys_are_written_as_strings(self) -> None:
        assert json.loads(json.dumps(self._refused())) == {"sections": {"1": _RUDE}}


# What a grandchild's failure looks like one level up: the inner relation's
# tree is a field of this row, not a message about it.
_INNER = {"items": {0: {"non_field_errors": ["No."]}}}


@pytest.mark.parametrize(
    ("path", "detail", "expected"),
    [
        pytest.param(
            _RowPath("sections", 1),
            _RUDE,
            {"sections": {1: _RUDE}},
            id="a-field-map-lands-at-the-rows-index",
        ),
        pytest.param(
            _RowPath("profile"), _RUDE, {"profile": _RUDE}, id="a-single-row-has-no-position"
        ),
        pytest.param(
            _RowPath("sections", 2),
            "Too rude.",
            {"sections": {2: {"non_field_errors": ["Too rude."]}}},
            id="a-string-is-the-rows-own-message",
        ),
        pytest.param(
            _RowPath("profile"),
            ["Too long.", "Too loud."],
            {"profile": {"non_field_errors": ["Too long.", "Too loud."]}},
            id="a-list-is-the-rows-own-messages",
        ),
        pytest.param(
            _RowPath("sections", 3),
            _INNER,
            {"sections": {3: _INNER}},
            id="a-nested-tree-is-a-field-map-and-lands-as-it-is",
        ),
    ],
)
def test_where_a_row_s_error_lands(path: _RowPath, detail: Any, expected: dict[Any, Any]) -> None:
    """``_RowPath`` alone, so each arm is pinned without a write."""
    assert path.namespace(detail) == expected


_NULL: dict[str, Any] = {"non_field_errors": ["This field cannot be null."]}
_SECTIONS = {"sections": ChildSpec(model=Section, fk="catalog")}
_TAGS = {"tags": ManyToManySpec(model=Tag)}


@pytest.mark.django_db
class TestANullRowIsRefusedBeforeAnythingIsWritten:
    """A declaration may let a null row through (``list[Row | None]``), and nothing
    in a relation spec says what one stands for. Read as a row, it was an empty
    mapping: a row created from nothing, or matched on nothing."""

    def test_in_an_owned_collection(self) -> None:
        rows = [{"title": "a"}, None, {"title": "b"}, None]
        with pytest.raises(InvalidArguments) as excinfo:
            create_from_input(Catalog, {"name": "c", "sections": rows}, relations=_SECTIONS)

        # Every null row, and none of the others: the refusal comes before the
        # first write, so the row at index 0 was not written either.
        assert excinfo.value.detail == {"sections": {1: _NULL, 3: _NULL}}
        assert not Section.objects.exists()

    def test_each_carries_the_code_drf_gives_a_null(self) -> None:
        with pytest.raises(InvalidArguments) as excinfo:
            create_from_input(Catalog, {"name": "c", "sections": [None]}, relations=_SECTIONS)

        assert coded(excinfo.value.detail) == {
            "sections": {0: {"non_field_errors": [("This field cannot be null.", "null")]}}
        }

    def test_in_a_many_to_many(self) -> None:
        with pytest.raises(InvalidArguments) as excinfo:
            create_from_input(
                Post, {"title": "t", "tags": [{"name": "orm"}, None]}, relations=_TAGS
            )

        assert excinfo.value.detail == {"tags": {1: _NULL}}
        assert not Tag.objects.exists()


@pytest.mark.django_db(transaction=True)
class TestANullRowIsRefusedBeforeAnythingIsWrittenAsync:
    async def test_in_an_owned_collection(self) -> None:
        rows = [{"title": "a"}, None]
        with pytest.raises(InvalidArguments) as excinfo:
            await acreate_from_input(Catalog, {"name": "c", "sections": rows}, relations=_SECTIONS)

        assert excinfo.value.detail == {"sections": {1: _NULL}}
        assert not await Section.objects.aexists()

    async def test_in_a_many_to_many(self) -> None:
        with pytest.raises(InvalidArguments) as excinfo:
            await acreate_from_input(
                Post, {"title": "t", "tags": [None, {"name": "orm"}]}, relations=_TAGS
            )

        assert excinfo.value.detail == {"tags": {0: _NULL}}
        assert not await Tag.objects.aexists()
