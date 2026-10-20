"""Tests for non-exported helpers in mutations/utils.py."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from django.core.exceptions import ObjectDoesNotExist

from django_service_specs.mutations.utils import (
    auto_now_field_names,
    coerce_to_dict,
    diff_attrs,
    dimension_field_names,
    filter_input,
    m2m_target_pks,
    resolve_update_fields,
    safe_getattr,
)
from django_service_specs.types.unset import UNSET
from tests.adapter_app.models import Document, Photo
from tests.relations_app.models import Author, Timestamped


class _RaisingFK:
    """Mimics a Django relation descriptor that raises when unset."""

    @property
    def author(self) -> Any:
        raise ObjectDoesNotExist("no related object")


class TestCoerceToDict:
    @pytest.mark.parametrize(
        ("data", "expected"),
        [
            pytest.param(None, {}, id="none-is-empty"),
            pytest.param({"a": 1}, {"a": 1}, id="dict"),
        ],
    )
    def test_a_mapping_or_nothing(self, data: Any, expected: dict[str, Any]) -> None:
        assert coerce_to_dict(data) == expected

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


@pytest.mark.parametrize(
    ("raw", "field_map", "exclude_fields", "expected"),
    [
        pytest.param({"a": UNSET, "b": 1}, None, None, {"b": 1}, id="drops-unset"),
        pytest.param(
            {"input_name": 1, "passthrough": 2},
            {"input_name": "model_attr"},
            None,
            {"model_attr": 1, "passthrough": 2},
            id="applies-field-map",
        ),
        pytest.param(
            {"a": 1, "b": 2}, {"a": "x"}, ["a"], {"b": 2}, id="excludes-against-input-names"
        ),
    ],
)
def test_filter_input(
    raw: dict[str, Any],
    field_map: dict[str, str] | None,
    exclude_fields: list[str] | None,
    expected: dict[str, Any],
) -> None:
    assert filter_input(raw, field_map=field_map, exclude_fields=exclude_fields) == expected


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
        class _Obj:
            x = 1
            y = 2

        changes = diff_attrs(_Obj(), {"x": 1, "y": 99})
        assert len(changes) == 1
        assert changes[0].field == "y"
        assert changes[0].new == 99
        assert changes[0].old == 2


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(None, [], id="none"),
        pytest.param([1, 2, 3], [1, 2, 3], id="pks-pass-through"),
    ],
)
def test_m2m_target_pks(value: Any, expected: list[Any]) -> None:
    assert m2m_target_pks(value) == expected


@pytest.mark.parametrize(
    ("instance", "expected"),
    [
        # ``Timestamped`` declares ``created_at`` with ``auto_now_add``, which is
        # left out: only ``auto_now`` is refreshed on an update.
        pytest.param(Timestamped(), ("updated_at",), id="auto-now-not-auto-now-add"),
        pytest.param(Author(), (), id="model-without-auto-now"),
    ],
)
def test_auto_now_field_names(instance: Any, expected: tuple[str, ...]) -> None:
    assert auto_now_field_names(instance) == expected


@pytest.mark.parametrize(
    ("instance", "changed", "expected"),
    [
        pytest.param(Photo(), ("book", "image"), ("w", "h"), id="a-changed-image-names-its-own"),
        pytest.param(Photo(), ("thumbnail",), (), id="an-image-declaring-none-names-nothing"),
        pytest.param(
            Document(), ("attachment", "title"), (), id="a-file-that-is-not-an-image-names-nothing"
        ),
    ],
)
def test_dimension_field_names(
    instance: Any, changed: tuple[str, ...], expected: tuple[str, ...]
) -> None:
    assert dimension_field_names(instance, changed) == expected


@pytest.mark.parametrize(
    ("update_fields", "changed", "derived", "expected"),
    [
        pytest.param(True, ("a", "b"), (), ["a", "b"], id="true-with-changes"),
        pytest.param(True, (), (), None, id="true-without-changes"),
        pytest.param(False, ("a",), (), None, id="false"),
        pytest.param(["x", "y"], ("a",), (), ["x", "y"], id="explicit-list"),
        pytest.param(
            True, ("title",), ("updated_at",), ["title", "updated_at"], id="derived-appended"
        ),
        pytest.param(True, (), ("updated_at",), None, id="derived-not-appended-with-no-changes"),
        pytest.param(False, ("title",), ("updated_at",), None, id="derived-not-appended-for-false"),
        pytest.param(
            ["title"], ("x",), ("updated_at",), ["title"], id="derived-not-appended-to-a-list"
        ),
        pytest.param(
            True,
            ("updated_at", "title"),
            ("updated_at",),
            ["updated_at", "title"],
            id="derived-already-changed-is-not-repeated",
        ),
    ],
)
def test_resolve_update_fields(
    update_fields: bool | list[str],
    changed: tuple[str, ...],
    derived: tuple[str, ...],
    expected: list[str] | None,
) -> None:
    assert resolve_update_fields(update_fields, changed, derived) == expected
