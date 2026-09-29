from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest

from django_service_specs.schema.utils import allow_null, is_json_native
from django_service_specs.types.unset import UNSET


class TestAllowNull:
    def test_the_type_becomes_a_list_with_null(self) -> None:
        assert allow_null({"type": "string", "format": "date"}) == {
            "type": ["string", "null"],
            "format": "date",
        }

    def test_the_type_keeps_its_place_before_the_other_keywords(self) -> None:
        widened = allow_null({"type": "object", "properties": {}, "required": ["a"]})

        assert list(widened) == ["type", "properties", "required"]

    def test_the_schema_passed_in_is_left_alone(self) -> None:
        schema = {"type": "integer"}

        widened = allow_null(schema)

        assert schema == {"type": "integer"}
        assert widened is not schema


class TestIsJsonNative:
    @pytest.mark.parametrize(
        "value",
        [None, "text", 0, 1.5, True, [1, "a", None], (1, 2), {"key": [{"nested": False}]}],
    )
    def test_a_value_json_encodes_as_itself_is_native(self, value: Any) -> None:
        assert is_json_native(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            Decimal("1.5"),
            dt.date(2026, 1, 1),
            dt.datetime(2026, 1, 1, 12, 0),
            len,
            UNSET,
            [1, Decimal("2")],
            (dt.date(2026, 1, 1),),
            {1: "an int key"},
            {"key": Decimal("1")},
        ],
    )
    def test_a_value_json_cannot_carry_is_not_native_however_deep(self, value: Any) -> None:
        assert is_json_native(value) is False
