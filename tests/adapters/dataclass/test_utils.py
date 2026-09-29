from __future__ import annotations

import dataclasses
import re
import typing
from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Any, Literal

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.adapters.dataclass.utils import (
    Shape,
    check_dataclass,
    encode,
    read_fields,
    scalar_type,
)
from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.types.unset import UNSET, UnsetType
from tests.adapters.dataclass.utils import Address, Colour


class _Pairs(Enum):
    # Values that are not JSON scalars: no wire can send one.
    A = (1, 2)


class _Nothing(Enum): ...


@dataclass
class _Node:
    children: list[_Node]


@dataclass
class _Ping:
    pong: _Pong | None = None


@dataclass
class _Pong:
    ping: _Ping | None = None


def _one(annotation: Any) -> tuple[str, Any]:
    """The shape of a single field annotated ``annotation``, read by ``read_fields``."""
    (fs,) = read_fields(dataclasses.make_dataclass("Probe", [("x", annotation)]))
    return fs.name, fs


def _read(annotation: Any) -> Any:
    return _one(annotation)[1]


# --- check_dataclass -------------------------------------------------------------------


def test_check_dataclass_accepts_a_dataclass_type() -> None:
    check_dataclass(Address, label="X")


@pytest.mark.parametrize("value", [int, Address("Oslo"), None])
def test_check_dataclass_refuses_the_rest_naming_it(value: Any) -> None:
    with pytest.raises(
        ImproperlyConfigured, match=re.escape(f"X takes a dataclass type; got {value!r}.")
    ):
        check_dataclass(value, label="X")


# --- read_fields: what is read -----------------------------------------------------------


@pytest.mark.parametrize(
    "annotation",
    [
        Annotated[str | None, FieldMarking.handle()],
        Annotated[str, FieldMarking.handle()] | None,
        typing.Optional[Annotated[str, FieldMarking.handle()]],  # noqa: UP045
    ],
)
def test_annotated_and_none_nest_either_way_round(annotation: Any) -> None:
    fs = _read(annotation)
    assert (fs.shape.type, fs.shape.nullable, fs.marking) == (
        "string",
        True,
        FieldMarking.handle(),
    )


def test_a_literal_holding_none_is_a_nullable_choice() -> None:
    shape = _read(Literal["a", "b", None]).shape
    assert (shape.type, shape.nullable, shape.choices) == ("string", True, ("a", "b"))


@pytest.mark.parametrize(
    ("annotation", "json_type"),
    [(Literal[1, 2], "integer"), (Literal[0.5], "number"), (Literal[True], "boolean")],
)
def test_a_literal_declares_the_json_type_its_values_share(annotation: Any, json_type: str) -> None:
    assert _read(annotation).shape.type == json_type


def test_an_element_keeps_its_own_nullability() -> None:
    shape = _read(list[int | None]).shape
    assert shape.items == Shape("integer", python=int, nullable=True)
    assert shape.nullable is False


def test_unset_type_is_omittable_and_adds_no_json_type() -> None:
    fs = _read(int | UnsetType)
    assert (fs.shape.type, fs.shape.nullable, fs.omittable, fs.required) == (
        "integer",
        False,
        True,
        False,
    )


def test_a_field_without_a_default_or_unset_type_is_required() -> None:
    fs = _read(int)
    assert (fs.has_default, fs.omittable, fs.required) == (False, False, True)


def test_shape_enum_is_the_enum_class_and_nothing_else() -> None:
    assert _read(Colour).shape.enum is Colour
    assert _read(Literal["a"]).shape.enum is None
    assert _read(str).shape.enum is None


def test_a_nested_dataclass_is_read_with_its_own_fields() -> None:
    shape = _read(Address).shape
    assert (shape.type, shape.python) == ("object", Address)
    assert [fs.name for fs in shape.fields] == ["city", "postcode"]


# --- read_fields: what is refused ----------------------------------------------------------


@pytest.mark.parametrize(
    ("annotation", "named"),
    [
        (typing.Any, "Any"),
        (object, "object"),
        (bytes, "bytes"),
        # A parametrized generic as it was written, which Python 3.10 would
        # otherwise print as its bare class.
        (dict[str, int], "dict[str, int]"),
        (set[int], "set[int]"),
        # Unparameterised: there is no element to declare.
        (list, "list"),
        (typing.List, "typing.List"),  # noqa: UP006
        (tuple[int, ...], "tuple[int, ...]"),
        # A union of two types has no single JSON type; nor does None alone.
        (int | str, "int | str"),
        (None, "None"),
        (UnsetType | None, "None"),
        # Choices whose values share no JSON type, or have none.
        (Literal["a", 1], "Literal"),
        (Literal[True, 1], "Literal"),
        (_Pairs, "_Pairs"),
        (_Nothing, "_Nothing"),
    ],
)
def test_an_annotation_with_no_json_type_is_refused_naming_field_and_annotation(
    annotation: Any, named: str
) -> None:
    with pytest.raises(ImproperlyConfigured) as caught:
        _read(annotation)
    message = str(caught.value)
    assert message.startswith("Probe.x: ")
    assert named in message
    assert "has no JSON type this adapter can declare" in message


def test_an_unmappable_element_is_refused_under_its_field() -> None:
    with pytest.raises(ImproperlyConfigured, match="Probe.x: .*dict.* has no JSON type"):
        _read(list[dict[str, int]])


def test_a_dataclass_that_contains_itself_is_refused() -> None:
    with pytest.raises(ImproperlyConfigured, match="_Node -> _Node: a dataclass that contains"):
        read_fields(_Node)
    with pytest.raises(ImproperlyConfigured, match="_Ping -> _Pong -> _Ping"):
        read_fields(_Ping)


def test_an_annotation_its_module_cannot_resolve_is_refused_by_class() -> None:
    @dataclass
    class Inner:
        y: int

    @dataclass
    class Outer:
        # A string under the future import, resolved against this module's
        # globals, where a class local to this function is not.
        inner: Inner

    with pytest.raises(ImproperlyConfigured, match="Outer: an annotation names .*'Inner'"):
        read_fields(Outer)


def test_two_markings_on_one_field_are_refused() -> None:
    annotation = Annotated[int, FieldMarking.handle(), FieldMarking.hidden()]
    with pytest.raises(ImproperlyConfigured, match="Probe.x: declares 2 FieldMarkings"):
        _read(annotation)


def test_annotated_metadata_that_is_not_a_marking_is_looked_through() -> None:
    fs = _read(Annotated[int, "a note"])
    assert (fs.shape.type, fs.marking) == ("integer", None)


# --- encode and scalar_type -----------------------------------------------------------------


def test_encode_passes_none_and_unset_through_whatever_the_shape() -> None:
    address = _read(Address).shape
    assert encode(address, None) is None
    assert encode(address, UNSET) is UNSET


def test_encode_reads_an_enum_by_value_even_where_a_str_is_declared() -> None:
    assert encode(Shape("string", python=str), Colour.BLUE) == "blue"


@pytest.mark.parametrize(
    ("value", "json_type"),
    [(True, "boolean"), (1, "integer"), (1.5, "number"), ("1", "string"), (None, None), ([], None)],
)
def test_scalar_type(value: Any, json_type: str | None) -> None:
    assert scalar_type(value) == json_type
