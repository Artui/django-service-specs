from __future__ import annotations

import dataclasses

import pytest

from django_service_specs.validation.validation_context import ValidationContext


def test_a_call_is_whole_unless_it_says_otherwise() -> None:
    context = ValidationContext("ada")
    assert (context.principal, context.target, context.partial) == ("ada", None, False)


def test_partial_follows_the_two_positional_fields() -> None:
    # Dispatch builds the context positionally, so the new field is trailing
    # and defaulted, and a caller written against principal and target alone
    # keeps working.
    context = ValidationContext("ada", "row", partial=True)
    assert (context.principal, context.target, context.partial) == ("ada", "row", True)


def test_the_context_is_frozen() -> None:
    context = ValidationContext("ada")
    with pytest.raises(dataclasses.FrozenInstanceError):
        context.partial = True  # ty: ignore[invalid-assignment]


def test_a_context_built_by_hand_carries_no_ambient_values() -> None:
    """Empty unless dispatch fills it, so a context built from a principal and
    a target is still a whole one."""
    assert dict(ValidationContext("ada", "row").ambient) == {}
