from __future__ import annotations

import dataclasses
from types import MappingProxyType

import pytest

from django_service_specs.validation.validation_context import ValidationContext


def test_a_call_is_whole_unless_it_says_otherwise() -> None:
    context = ValidationContext("ada")
    assert (context.principal, context.target, context.partial) == ("ada", None, False)


def test_partial_follows_the_two_positional_fields() -> None:
    # Dispatch builds the context positionally, so ``partial`` trails and is
    # defaulted, and a caller written against principal and target alone
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


def test_two_contexts_differing_in_ambient_alone_are_equal() -> None:
    """Two contexts of one call are one context, whatever the seeds resolved to."""
    one = ValidationContext("ada", "row", ambient=MappingProxyType({"tenant": "a"}))
    other = ValidationContext("ada", "row", ambient=MappingProxyType({"tenant": "b"}))
    assert one == other


def test_a_context_carrying_ambient_values_is_hashable() -> None:
    """A mapping proxy cannot be hashed, so ``ambient`` stays out of the hash
    a frozen dataclass derives from its compared fields."""
    context = ValidationContext("ada", "row", ambient=MappingProxyType({"tenant": "a"}))
    assert hash(context) == hash(ValidationContext("ada", "row"))


def test_a_context_built_by_hand_resolves_no_target_name() -> None:
    assert dict(ValidationContext("ada", "row").resolved) == {}


def test_two_contexts_differing_in_resolved_alone_are_equal() -> None:
    """The target is compared as ``target``; its pool name says nothing more."""
    one = ValidationContext("ada", "row", resolved=MappingProxyType({"instance": "row"}))
    other = ValidationContext("ada", "row")
    assert one == other


def test_a_context_carrying_a_resolved_target_is_hashable() -> None:
    context = ValidationContext("ada", "row", resolved=MappingProxyType({"instance": "row"}))
    assert hash(context) == hash(ValidationContext("ada", "row"))


def test_a_context_built_by_hand_carries_an_empty_call_context() -> None:
    """A plain ``dict`` every context has, so a Validator declaring nothing
    else still reads and writes one without guarding for ``None``."""
    context = ValidationContext("ada", "row")
    assert type(context.call_context) is dict
    assert context.call_context == {}


def test_each_context_built_by_hand_has_a_call_context_of_its_own() -> None:
    """A fresh dict per context, never one shared default every call writes to."""
    assert ValidationContext("ada").call_context is not ValidationContext("ada").call_context


def test_the_call_context_is_the_object_handed_in() -> None:
    """The same dict, not a copy: what a Validator writes is there for every
    later stage of the call that holds it."""
    shared: dict[str, object] = {}
    context = ValidationContext("ada", call_context=shared)
    context.call_context["tenant"] = "a"
    assert shared == {"tenant": "a"}


def test_the_call_context_trails_every_other_field() -> None:
    """Built positionally as dispatch builds the rest, so no existing
    construction changes."""
    shared: dict[str, object] = {"request": None}
    context = ValidationContext(
        "ada", "row", True, MappingProxyType({}), MappingProxyType({}), shared
    )
    assert context.call_context is shared


def test_two_contexts_differing_in_call_context_alone_are_equal() -> None:
    one = ValidationContext("ada", "row", call_context={"tenant": "a"})
    assert one == ValidationContext("ada", "row", call_context={"tenant": "b"})


def test_a_context_carrying_a_call_context_is_hashable() -> None:
    """A dict cannot be hashed, so the call's context stays out of the hash."""
    context = ValidationContext("ada", "row", call_context={"tenant": "a"})
    assert hash(context) == hash(ValidationContext("ada", "row"))
