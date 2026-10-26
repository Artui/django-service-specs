"""The helpers ``types/`` shares with the specs and the affordance phase."""

from __future__ import annotations

import dataclasses
import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Exists, F, OuterRef, Q
from django.utils.translation import gettext_lazy

from django_service_specs.output.output import OutputField
from django_service_specs.parameters.parameters import Parameter
from django_service_specs.pool.reserved_pool_seeds import RESERVED_POOL_SEEDS
from django_service_specs.types.affordance import Affordance
from django_service_specs.types.unset import UNSET
from django_service_specs.types.utils import (
    OUTPUT_FIELD_SCHEMA_KEYWORDS,
    PARAMETER_SCHEMA_KEYWORDS,
    PER_CALL_POOL_NAMES,
    affordance_alias,
    is_json_native,
    is_row_condition,
)
from tests.dispatch_app.models import Note


def test_the_per_call_names_and_the_ambient_seeds_partition_the_reserved_names() -> None:
    # ``types/`` cannot import ``pool/``, so the per-call names are written out
    # rather than derived. This is what holds the two lists together: a name
    # reserved later has to be placed on one side or the other, deliberately.
    # ``serializer`` is the one exception: the DRF adapter's per-call name,
    # which this kernel never seeds and so never reserves. ``call_context`` is
    # ambient: the transport's dict outlives the call, and an affordance
    # condition may read it as it reads a seed. ``shapes`` is per call: what
    # the caller sent is no surrounding of the call.
    assert PER_CALL_POOL_NAMES - {"serializer"} <= RESERVED_POOL_SEEDS
    ambient = RESERVED_POOL_SEEDS - PER_CALL_POOL_NAMES
    assert ambient == {"user", "progress", "call_context"}


def test_a_condition_naming_the_shapes_is_refused_at_its_declaration() -> None:
    """A condition reading what the caller sent would let the caller decide availability."""

    def by_query(*, shapes: Any) -> bool:
        return "query" in shapes

    with pytest.raises(ImproperlyConfigured, match="'shapes'"):
        Affordance(code="c", reason="r", when=by_query)


def test_an_orm_expression_is_a_row_condition_and_a_callable_is_not() -> None:
    assert is_row_condition(Q(archived=False))
    assert is_row_condition(Exists(Note.objects.filter(pk=OuterRef("pk"))))
    assert is_row_condition(F("archived"))
    assert not is_row_condition(lambda: True)
    assert not is_row_condition(True)


def test_an_alias_cannot_shadow_a_model_field() -> None:
    # Django refuses ``__`` in a field name, so a double-underscored alias is
    # never one.
    assert affordance_alias("rename", "note_archived") == "affordance__rename__note_archived"


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
            gettext_lazy("a lazy translation"),
            ["a", {"nested": gettext_lazy("deeper")}],
            {"a", "set"},
        ],
    )
    def test_a_value_json_cannot_carry_is_not_native_however_deep(self, value: Any) -> None:
        assert is_json_native(value) is False


class TestSchemaKeywords:
    @pytest.mark.parametrize(
        ("keywords", "declaration"),
        [
            pytest.param(PARAMETER_SCHEMA_KEYWORDS, Parameter, id="parameter"),
            pytest.param(OUTPUT_FIELD_SCHEMA_KEYWORDS, OutputField, id="output-field"),
        ],
    )
    def test_every_owner_named_is_a_field_of_the_declaration(
        self, keywords: Any, declaration: Any
    ) -> None:
        """The refusal sends an author to these names, so each must be one
        they can set."""
        fields = {field.name for field in dataclasses.fields(declaration)}
        owners = {owner for named in keywords.values() for owner in named}
        assert owners <= fields

    def test_neither_table_can_be_changed_by_a_reader(self) -> None:
        with pytest.raises(TypeError):
            PARAMETER_SCHEMA_KEYWORDS["pattern"] = ("format",)  # ty: ignore[invalid-assignment]
