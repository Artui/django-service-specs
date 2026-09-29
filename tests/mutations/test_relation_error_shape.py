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
from django_service_specs.mutations.utils import _RowPath
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.relations.child_spec import ChildSpec
from django_service_specs.relations.many_to_many_spec import ManyToManySpec
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


class TestWhereARowsErrorLands:
    """``_RowPath`` alone, so each arm is pinned without a write."""

    def test_a_field_map_lands_at_the_rows_index(self) -> None:
        assert _RowPath("sections", 1).namespace(_RUDE) == {"sections": {1: _RUDE}}

    def test_a_single_row_has_no_position(self) -> None:
        assert _RowPath("profile").namespace(_RUDE) == {"profile": _RUDE}

    def test_a_string_is_the_rows_own_message(self) -> None:
        assert _RowPath("sections", 2).namespace("Too rude.") == {
            "sections": {2: {"non_field_errors": ["Too rude."]}}
        }

    def test_a_list_is_the_rows_own_messages(self) -> None:
        assert _RowPath("profile").namespace(["Too long.", "Too loud."]) == {
            "profile": {"non_field_errors": ["Too long.", "Too loud."]}
        }

    def test_a_nested_tree_is_a_field_map_and_lands_as_it_is(self) -> None:
        # What a grandchild's failure looks like one level up: the inner
        # relation's tree is a field of this row, not a message about it.
        inner = {"items": {0: {"non_field_errors": ["No."]}}}

        assert _RowPath("sections", 3).namespace(inner) == {"sections": {3: inner}}


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
