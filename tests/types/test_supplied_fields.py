from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from django_service_specs.types.supplied_fields import supplied_fields
from django_service_specs.types.unset import UNSET, UnsetType
from tests.dispatch_app.models import Note


@dataclass
class _BookPatch:
    title: str | UnsetType = UNSET
    pk: int | None = None


@dataclass
class _AuthorPatch:
    name: str | UnsetType = UNSET
    bio: str | None | UnsetType = UNSET
    books: list[_BookPatch] | UnsetType = UNSET
    lead: _BookPatch | UnsetType = UNSET
    note: Note | UnsetType = UNSET


def test_a_dataclass_drops_unset_and_keeps_none_in_field_order() -> None:
    patch = _AuthorPatch(bio=None, name="Ada")

    assert list(supplied_fields(patch).items()) == [("name", "Ada"), ("bio", None)]


def test_nested_values_are_the_caller_s_own_objects() -> None:
    lead = _BookPatch()
    books = [_BookPatch(title="Notes")]
    note = Note(title="Plan")

    supplied = supplied_fields(_AuthorPatch(books=books, lead=lead, note=note))

    # Shallow: the nested inputs keep their own UNSET fields, and nothing is copied.
    assert supplied == {"books": books, "lead": lead, "note": note}
    assert supplied["books"] is books
    assert supplied["lead"] is lead
    assert supplied["lead"].title is UNSET
    assert supplied["note"] is note


def test_a_field_declared_init_false_is_left_out() -> None:
    @dataclass
    class Patch:
        name: str | UnsetType = UNSET
        slug: str = field(init=False, default="computed")

    assert supplied_fields(Patch(name="Ada")) == {"name": "Ada"}


def test_a_mapping_drops_unset_and_keeps_none() -> None:
    lead = {"title": UNSET}

    supplied = supplied_fields({"name": UNSET, "bio": None, "lead": lead})

    assert supplied == {"bio": None, "lead": lead}
    assert supplied["lead"] is lead


@pytest.mark.parametrize("data", [_AuthorPatch, 3, None])
def test_anything_but_a_dataclass_instance_or_a_mapping_is_refused(data: object) -> None:
    with pytest.raises(TypeError, match="takes a dataclass instance or a mapping"):
        supplied_fields(data)
