from __future__ import annotations

import datetime as dt
import re
import typing
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, Literal

import pytest
from django.core.exceptions import ImproperlyConfigured
from pydantic import (
    AliasChoices,
    AliasPath,
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    computed_field,
    create_model,
)

from django_service_specs.adapters.pydantic.utils import (
    MAX_APPEARANCES,
    FieldShape,
    Shape,
    check_model,
    fields_of,
    inputs,
    is_json_native,
    read_fields,
)
from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.types.unset import UNSET, UnsetType
from tests.adapters.pydantic.utils import Address, Colour, Leaves, Node


class _Pairs(Enum):
    # Values that are not JSON scalars: no wire can send one.
    A = (1, 2)


class _Nothing(Enum): ...


class _Tags(RootModel[list[str]]): ...


class _Holder(BaseModel):
    tags: _Tags


class _Ping(BaseModel):
    pong: _Pong | None = None


class _Pong(BaseModel):
    ping: _Ping | None = None


class _Early(BaseModel):
    # Names a class defined below it, so pydantic builds it incomplete.
    later: _Later | None = None


class _Later(BaseModel):
    value: int


class _Dangling(BaseModel):
    # Names a class that is never defined anywhere.
    ghost: _Ghost  # noqa: F821 - unresolvable on purpose


class _Aliased(BaseModel):
    plain: int
    aliased: int = Field(alias="a")
    split: int = Field(validation_alias="in_wire", serialization_alias="out_wire")
    hidden: int = Field(0, exclude=True)

    @computed_field(alias="twice")
    @property
    def double(self) -> int:
        return self.plain * 2


def _one(annotation: Any, default: Any = ..., **config: Any) -> FieldShape:
    """The one field of a model declaring ``x: annotation``, as ``read_fields`` reads it."""
    model = create_model("Probe", __config__=ConfigDict(**config), x=(annotation, default))
    (fs,) = read_fields(model)
    return fs


def _depth(shape: Shape) -> int:
    """How many levels of ``Node`` a shape describes before the bound cuts it."""
    children = next(fs for fs in fields_of(shape) if fs.name == "children").shape.items
    assert children is not None
    return 1 if children.fields is None else 1 + _depth(children)


class TestCheckModel:
    def test_accepts_a_model_class(self) -> None:
        check_model(Address, label="Probe")

    @pytest.mark.parametrize("value", [dict, Address(city="Oslo"), list[int], "Address"])
    def test_refuses_anything_but_a_model_class(self, value: Any) -> None:
        with pytest.raises(ImproperlyConfigured, match="Probe takes a pydantic model class") as ex:
            check_model(value, label="Probe")
        assert repr(value) in str(ex.value)

    def test_a_root_model_is_refused(self) -> None:
        # It validates one value, not named arguments, so it has no parameters.
        with pytest.raises(ImproperlyConfigured, match="not a RootModel"):
            check_model(_Tags, label="Probe")
        with pytest.raises(ImproperlyConfigured, match="_Holder.tags: _Tags has no JSON type"):
            read_fields(_Holder)


class TestAnnotations:
    @pytest.mark.parametrize(
        ("annotation", "json_type", "fmt"),
        [
            (str, "string", None),
            (int, "integer", None),
            (float, "number", None),
            (bool, "boolean", None),
            (Decimal, "string", "decimal"),
            (dt.datetime, "string", "date-time"),
            (dt.date, "string", "date"),
        ],
    )
    def test_each_scalar_is_read_from_the_shared_table(
        self, annotation: Any, json_type: str, fmt: str | None
    ) -> None:
        shape = _one(annotation).shape
        assert (shape.type, shape.format, shape.python) == (json_type, fmt, annotation)

    @pytest.mark.parametrize(
        "annotation",
        [
            Annotated[str | None, "m"],
            Annotated[str, "m"] | None,
            typing.Optional[Annotated[str, "m"]],  # noqa: UP045
        ],
    )
    def test_annotated_and_none_nest_either_way_round(self, annotation: Any) -> None:
        shape = _one(annotation).shape
        assert (shape.type, shape.nullable) == ("string", True)

    def test_a_literal_holding_none_is_a_nullable_choice(self) -> None:
        shape = _one(Literal["a", "b", None]).shape
        assert (shape.type, shape.nullable, shape.choices, shape.enum) == (
            "string",
            True,
            ("a", "b"),
            None,
        )

    def test_an_enum_is_a_choice_of_its_values(self) -> None:
        shape = _one(Colour).shape
        assert (shape.type, shape.choices, shape.enum) == ("string", ("red", "blue"), Colour)

    def test_a_list_element_keeps_its_own_nullability(self) -> None:
        shape = _one(list[int | None]).shape
        assert shape.type == "array"
        assert shape.items == Shape("integer", python=int, nullable=True)

    def test_a_str_keyed_dict_is_an_object_with_no_fields(self) -> None:
        shape = _one(dict[str, Any] | None).shape
        assert shape == Shape("object", python=dict, nullable=True)
        assert shape.model is None

    def test_a_nested_model_is_read_with_its_own_fields(self) -> None:
        shape = _one(Address).shape
        assert (shape.type, shape.model) == ("object", Address)
        assert shape.fields is not None
        assert [fs.name for fs in shape.fields] == ["city", "postcode"]

    @pytest.mark.parametrize(
        ("annotation", "name"),
        [
            (Any, "Any"),
            (int | str, "int | str"),
            (set[int], "set[int]"),
            (dict[int, str], "dict[int, str]"),
            (dict, "dict"),
            (tuple[int, ...], "tuple[int, ...]"),
            (Literal["a", 1], "Literal['a', 1]"),
            (_Pairs, "_Pairs"),
            (_Nothing, "_Nothing"),
            (list[int | str], "int | str"),
        ],
    )
    def test_an_annotation_with_no_json_type_is_refused_naming_field_and_annotation(
        self, annotation: Any, name: str
    ) -> None:
        with pytest.raises(ImproperlyConfigured) as caught:
            _one(annotation)
        message = str(caught.value)
        assert message.startswith("Probe.x: ")
        assert re.search(rf"(typing\.)?{re.escape(name)} has no JSON type", message), message
        # The refusal says what would have been accepted.
        assert "a pydantic model, dict[str, ...], or a list of any of these" in message

    def test_unset_type_is_refused_here_where_the_dataclass_adapter_reads_it(self) -> None:
        with pytest.raises(ImproperlyConfigured, match="Probe.x: .*UnsetType has no JSON type"):
            _one(str | UnsetType, UNSET, arbitrary_types_allowed=True)


class TestMarkings:
    def test_a_marking_is_found_either_side_of_none(self) -> None:
        assert _one(Annotated[str | None, FieldMarking.handle()]).marking == FieldMarking.handle()
        assert _one(Annotated[str, FieldMarking.label()] | None).marking == FieldMarking.label()

    def test_metadata_that_is_not_a_marking_is_looked_through(self) -> None:
        fs = _one(Annotated[int, Field(ge=0), "note"])
        assert (fs.shape.type, fs.marking) == ("integer", None)

    def test_two_markings_on_one_field_are_refused(self) -> None:
        with pytest.raises(ImproperlyConfigured, match="Probe.x: declares 2 FieldMarkings"):
            _one(Annotated[int, FieldMarking.handle(), FieldMarking.hidden()])


class TestNames:
    def test_each_field_is_named_as_pydantic_reads_and_writes_it(self) -> None:
        names = [
            (fs.name, fs.input_name, fs.output_name, fs.computed) for fs in read_fields(_Aliased)
        ]
        assert names == [
            ("plain", "plain", "plain", False),
            ("aliased", "a", "a", False),
            ("split", "in_wire", "out_wire", False),
            # Excluded: an input, never output.
            ("hidden", "hidden", None, False),
            # Computed: output, never an input.
            ("double", "double", "twice", True),
        ]
        assert [fs.name for fs in inputs(read_fields(_Aliased))] == [
            "plain",
            "aliased",
            "split",
            "hidden",
        ]

    @pytest.mark.parametrize("alias", [AliasPath("a", 0), AliasChoices("a", "b")])
    def test_an_alias_that_is_not_one_name_is_refused(self, alias: Any) -> None:
        with pytest.raises(
            ImproperlyConfigured, match="Probe.x: validation_alias .* is not one name"
        ):
            _one(int, Field(validation_alias=alias))

    def test_a_model_validating_by_name_is_named_by_field_name(self) -> None:
        fs = _one(int, Field(alias="wire"), validate_by_alias=False, validate_by_name=True)
        assert (fs.input_name, fs.output_name) == ("x", "wire")


class TestRequiredAndDefault:
    def test_a_field_with_no_default_is_required(self) -> None:
        fs = _one(int)
        assert (fs.required, fs.default) == (True, UNSET)

    @pytest.mark.parametrize(
        ("annotation", "default"),
        [
            (int, 3),
            (str, "a"),
            (int | None, None),
            (list[int], [1, 2]),
            (dict[str, list[bool]], {"k": [True]}),
        ],
    )
    def test_a_json_native_default_is_reported(self, annotation: Any, default: Any) -> None:
        fs = _one(annotation, default)
        assert (fs.required, fs.default) == (False, default)

    @pytest.mark.parametrize(
        ("annotation", "default"),
        [(Decimal, Decimal("1.5")), (dt.date, dt.date(2024, 1, 1)), (Colour, Colour.RED)],
    )
    def test_a_default_json_cannot_carry_is_left_out_and_the_field_stays_optional(
        self, annotation: Any, default: Any
    ) -> None:
        fs = _one(annotation, default)
        assert (fs.required, fs.default) == (False, UNSET)

    def test_a_default_factory_is_not_reported_and_the_field_stays_optional(self) -> None:
        fs = _one(list[int], Field(default_factory=list))
        assert (fs.required, fs.default) == (False, UNSET)

    def test_help_and_label_are_the_description_and_title(self) -> None:
        fs = _one(int, Field(description="How many.", title="Count"))
        assert (fs.help, fs.label) == ("How many.", "Count")
        assert (_one(int).help, _one(int).label) == (None, None)


class TestAppearanceBound:
    def test_the_bound_is_four_appearances_as_drfs_has_it(self) -> None:
        assert MAX_APPEARANCES == 4

    def test_a_tree_is_described_to_the_bound_and_no_further(self) -> None:
        top = Shape("object", python=Node, fields=read_fields(Node))
        assert _depth(top) == MAX_APPEARANCES

    def test_the_first_level_past_the_bound_is_an_object_with_no_fields(self) -> None:
        shape = Shape("object", python=Node, fields=read_fields(Node))
        for _ in range(MAX_APPEARANCES):
            (_, children) = fields_of(shape)
            items = children.shape.items
            assert items is not None
            shape = items
        assert (shape.type, shape.model, shape.fields) == ("object", Node, None)

    def test_mutual_recursion_is_bounded_per_model(self) -> None:
        (ping,) = read_fields(_Pong)
        depth = 1
        shape = ping.shape
        while shape.fields is not None:
            (next_field,) = shape.fields
            shape = next_field.shape
            depth += 1
        # _Pong and _Ping alternate, four appearances of each after the root.
        assert depth == 2 * MAX_APPEARANCES
        assert (shape.model, shape.nullable) == (_Pong, True)

    def test_siblings_are_on_different_paths_and_described_in_full(self) -> None:
        fields = read_fields(Leaves)
        assert len(fields) > MAX_APPEARANCES
        assert all(fs.shape.fields is not None for fs in fields)

    def test_a_truncated_node_is_read_afresh_when_walked(self) -> None:
        cut = Shape("object", python=Node)
        assert [fs.name for fs in fields_of(cut)] == ["name", "children"]


class TestCompletion:
    def test_a_model_naming_a_later_class_is_completed_when_read(self) -> None:
        (later,) = read_fields(_Early)
        assert later.shape.model is _Later
        assert _Early.__pydantic_complete__

    def test_a_model_naming_a_class_that_does_not_exist_is_refused_by_model(self) -> None:
        with pytest.raises(ImproperlyConfigured, match="_Dangling: an annotation names .*_Ghost"):
            read_fields(_Dangling)


class TestIsJsonNative:
    @pytest.mark.parametrize(
        ("value", "native"),
        [
            ("a", True),
            (1, True),
            (1.5, True),
            (False, True),
            (None, True),
            ([1, ("a", None)], True),
            ({"k": {"j": [1]}}, True),
            ({1: "a"}, False),
            ([Decimal("1")], False),
            (Decimal("1"), False),
            (Colour.RED, False),
        ],
    )
    def test_whether_a_value_survives_json_as_itself(self, value: Any, native: bool) -> None:
        assert is_json_native(value) is native
