from __future__ import annotations

import datetime as dt
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, Optional

import pytest
from django.db import models
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy

from django_service_specs.adapters.utils import (
    SCALARS,
    choice_labels,
    choice_pairs,
    scalar_type,
    strip,
)
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
            ("1", "string"),
            (None, None),
            (Decimal("1"), None),
            ([], None),
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

    def test_extras_are_collected_from_every_level_innermost_first(self) -> None:
        # The order a library building the type applies them in: each layer
        # as written, the innermost first.
        annotation = Annotated[Annotated[int, "a", "b"] | None, "c", "d"]
        assert strip(annotation) == (int, True, False, ("a", "b", "c", "d"))

    def test_unset_type_is_omittable_and_adds_no_type(self) -> None:
        assert strip(str | None | UnsetType) == (str, True, True, ())

    def test_a_union_of_two_types_is_returned_as_the_union(self) -> None:
        base, nullable, omittable, extras = strip(int | str | None)
        assert (base, nullable, omittable, extras) == (int | str | None, True, False, ())

    def test_a_plain_annotation_is_returned_unchanged(self) -> None:
        assert strip(int) == (int, False, False, ())


class _Plain(Enum):
    RED = "red"


class _Shade(models.TextChoices):
    LIGHT = "l", "Light"
    DARK = "d", gettext_lazy("Dark")


def test_a_literal_has_no_labels() -> None:
    assert choice_labels(None) is None


def test_a_plain_enum_has_no_labels() -> None:
    assert choice_labels(_Plain) is None


def test_a_django_choices_enum_labels_each_value_and_keeps_a_lazy_label_lazy() -> None:
    labels = choice_labels(_Shade)
    assert labels == (("l", "Light"), ("d", "Dark"))
    assert labels is not None
    assert isinstance(labels[1][1], Promise)


def test_the_pairs_an_output_field_presents_render_a_lazy_label() -> None:
    # The pairs are the display a payload carries, so a lazy label is rendered
    # here, in the language active for this call, and a plain ``str`` leaves.
    pairs = choice_pairs(("l", "d"), _Shade)
    assert pairs == (("l", "Light"), ("d", "Dark"))
    assert pairs is not None
    assert all(type(display) is str for _, display in pairs)


def test_the_pairs_of_choices_with_no_labels_are_each_value_s_str() -> None:
    assert choice_pairs((1, 2), None) == ((1, "1"), (2, "2"))
    assert choice_pairs(None, None) is None
