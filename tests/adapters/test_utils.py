from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Annotated, Any, Optional

import pytest

from django_service_specs.adapters.utils import SCALARS, scalar_type, strip
from django_service_specs.types.unset import UnsetType


class TestScalars:
    def test_each_scalar_declares_its_json_type_and_format(self) -> None:
        expected = {
            str: ("string", None),
            int: ("integer", None),
            float: ("number", None),
            bool: ("boolean", None),
            Decimal: ("string", "decimal"),
            dt.datetime: ("string", "date-time"),
            dt.date: ("string", "date"),
        }
        assert expected == SCALARS

    def test_a_subclass_is_not_read_as_its_base(self) -> None:
        # Looked up by identity: bool is not an integer, datetime is not a date.
        assert SCALARS[bool] != SCALARS[int]
        assert SCALARS[dt.datetime] != SCALARS[dt.date]


class TestScalarType:
    @pytest.mark.parametrize(
        ("value", "json_type"),
        [
            (True, "boolean"),
            (1, "integer"),
            (1.5, "number"),
            ("a", "string"),
            (None, None),
            (Decimal("1"), None),
        ],
    )
    def test_the_json_type_of_a_value_bool_first(self, value: Any, json_type: str | None) -> None:
        assert scalar_type(value) == json_type


class TestStrip:
    @pytest.mark.parametrize(
        "annotation",
        [
            Annotated[Optional[str], "m"],  # noqa: UP045 - typing.Union is what this spells
            Optional[Annotated[str, "m"]],  # noqa: UP045
            Annotated[str | None, "m"],
            Annotated[str, "m"] | None,
        ],
    )
    def test_annotated_and_none_nest_either_way_round(self, annotation: Any) -> None:
        assert strip(annotation) == (str, True, False, ("m",))

    def test_extras_are_collected_from_every_level(self) -> None:
        assert strip(Annotated[Annotated[int, "a"] | None, "b"]) == (int, True, False, ("b", "a"))

    def test_unset_type_is_omittable_and_adds_no_type(self) -> None:
        assert strip(str | None | UnsetType) == (str, True, True, ())

    def test_a_union_of_two_types_is_returned_as_the_union(self) -> None:
        base, nullable, omittable, extras = strip(int | str | None)
        assert (base, nullable, omittable, extras) == (int | str | None, True, False, ())

    def test_a_plain_annotation_is_returned_unchanged(self) -> None:
        assert strip(int) == (int, False, False, ())
