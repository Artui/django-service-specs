"""Tests for non-exported helpers in mutations/utils.py."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

import pytest
from django.core.exceptions import ObjectDoesNotExist

from django_service_specs.mutations.utils import (
    auto_now_field_names,
    coerce_to_dict,
    diff_attrs,
    filter_input,
    m2m_target_pks,
    resolve_update_fields,
    safe_getattr,
    write_values,
)
from django_service_specs.types.unset import UNSET
from tests.adapter_app.models import Document
from tests.relations_app.models import Author, Post, Timestamped


class _RaisingFK:
    """Mimics a Django relation descriptor that raises when unset."""

    @property
    def author(self) -> Any:
        raise ObjectDoesNotExist("no related object")


class TestCoerceToDict:
    def test_none(self) -> None:
        assert coerce_to_dict(None) == {}

    def test_dict(self) -> None:
        assert coerce_to_dict({"a": 1}) == {"a": 1}

    def test_a_field_declared_init_false_is_left_out(self) -> None:
        # The dataclass computes it rather than taking it, so it is no input:
        # written to the row, a value nobody sent would land in a column.
        @dataclass
        class _Computed:
            title: str
            views: int = field(init=False)

            def __post_init__(self) -> None:
                self.views = 99

        assert coerce_to_dict(_Computed(title="hi")) == {"title": "hi"}

    def test_object_with_dict(self) -> None:
        class _Obj:
            def __init__(self) -> None:
                self.x = 1

        assert coerce_to_dict(_Obj()) == {"x": 1}

    def test_unsupported_raises(self) -> None:
        with pytest.raises(TypeError):
            coerce_to_dict(123)


class TestFilterInput:
    def test_drops_unset(self) -> None:
        assert filter_input({"a": UNSET, "b": 1}, field_map=None, exclude_fields=None) == {"b": 1}

    def test_applies_field_map(self) -> None:
        result = filter_input(
            {"input_name": 1, "passthrough": 2},
            field_map={"input_name": "model_attr"},
            exclude_fields=None,
        )
        assert result == {"model_attr": 1, "passthrough": 2}

    def test_excludes_against_input_names(self) -> None:
        result = filter_input(
            {"a": 1, "b": 2},
            field_map={"a": "x"},
            exclude_fields=["a"],
        )
        assert result == {"b": 2}


class TestSafeGetattr:
    def test_returns_value(self) -> None:
        class _Obj:
            x = 5

        assert safe_getattr(_Obj(), "x") == 5

    def test_missing_returns_unset(self) -> None:
        class _Obj: ...

        assert safe_getattr(_Obj(), "missing") is UNSET

    def test_object_does_not_exist_returns_unset(self) -> None:
        assert safe_getattr(_RaisingFK(), "author") is UNSET


class TestDiffAttrs:
    def test_only_returns_diffs(self) -> None:
        changes = diff_attrs(Post(title="t", views=2), {"title": "t", "views": 99})
        assert len(changes) == 1
        assert changes[0].field == "views"
        assert changes[0].new == 99
        assert changes[0].old == 2


class TestM2mTargetPks:
    def test_none(self) -> None:
        assert m2m_target_pks(None) == []

    def test_pks_passthrough(self) -> None:
        assert m2m_target_pks([1, 2, 3]) == [1, 2, 3]


class TestAutoNowFieldNames:
    def test_returns_auto_now_fields(self) -> None:
        assert auto_now_field_names(Timestamped()) == ("updated_at",)

    def test_excludes_auto_now_add(self) -> None:
        assert "created_at" not in auto_now_field_names(Timestamped())

    def test_model_without_auto_now(self) -> None:
        assert auto_now_field_names(Author()) == ()


class TestResolveUpdateFields:
    def test_true_with_changes(self) -> None:
        assert resolve_update_fields(True, ("a", "b")) == ["a", "b"]

    def test_true_without_changes(self) -> None:
        assert resolve_update_fields(True, ()) is None

    def test_false(self) -> None:
        assert resolve_update_fields(False, ("a",)) is None

    def test_explicit_list(self) -> None:
        assert resolve_update_fields(["x", "y"], ("a",)) == ["x", "y"]

    def test_auto_now_fields_appended(self) -> None:
        result = resolve_update_fields(True, ("title",), ("updated_at",))
        assert result == ["title", "updated_at"]

    def test_auto_now_fields_not_appended_when_no_changes(self) -> None:
        assert resolve_update_fields(True, (), ("updated_at",)) is None

    def test_auto_now_fields_not_appended_when_false(self) -> None:
        assert resolve_update_fields(False, ("title",), ("updated_at",)) is None

    def test_auto_now_fields_not_appended_for_explicit_list(self) -> None:
        assert resolve_update_fields(["title"], ("x",), ("updated_at",)) == ["title"]

    def test_auto_now_field_already_in_changed_no_dup(self) -> None:
        result = resolve_update_fields(True, ("updated_at", "title"), ("updated_at",))
        assert result == ["updated_at", "title"]


class TestWriteValues:
    def test_a_file_is_written_through_its_field_s_save_form_data(self) -> None:
        # As a ModelForm writes it, so a field overriding how it stores a file is honoured.
        row = Document(title="Notes")
        attachment = Document._meta.get_field("attachment")
        with patch.object(attachment, "save_form_data") as save_form_data:
            write_values(row, {"title": "New", "attachment": ""})
        save_form_data.assert_called_once_with(row, "")
        assert row.title == "New"
