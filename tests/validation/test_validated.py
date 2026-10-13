from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import pytest

from django_service_specs.validation.validated import Validated


@dataclass
class _Note:
    title: str


def test_a_validator_binds_nothing_unless_it_says_so() -> None:
    validated = Validated(values={"title": "Dune"}, data={"title": "Dune"})
    assert dict(validated.pool) == {}


def test_the_data_may_be_an_object_beside_its_fields() -> None:
    note = _Note("Dune")
    validated = Validated(values={"title": "Dune"}, data=note, pool={"form": "bound"})
    assert (validated.values, validated.data, dict(validated.pool)) == (
        {"title": "Dune"},
        note,
        {"form": "bound"},
    )


def test_it_is_frozen() -> None:
    validated = Validated(values={}, data={})
    with pytest.raises(dataclasses.FrozenInstanceError):
        validated.data = None  # ty: ignore[invalid-assignment]
