from __future__ import annotations

from types import MappingProxyType

from django_service_specs.output.presentation_context import PresentationContext


def test_two_contexts_differing_in_ambient_alone_are_equal() -> None:
    """Two contexts of one call are one context, whatever the seeds resolved to."""
    one = PresentationContext("ada", "row", ambient=MappingProxyType({"tenant": "a"}))
    other = PresentationContext("ada", "row", ambient=MappingProxyType({"tenant": "b"}))
    assert one == other


def test_a_context_carrying_ambient_values_is_hashable_where_its_target_is() -> None:
    """A mapping proxy cannot be hashed, so ``ambient`` stays out of the hash
    a frozen dataclass derives from its compared fields; the context hashes
    whenever its principal and target do."""
    context = PresentationContext("ada", "row", ambient=MappingProxyType({"tenant": "a"}))
    assert hash(context) == hash(PresentationContext("ada", "row"))


def test_a_context_built_by_hand_carries_an_empty_call_context_and_no_shapes() -> None:
    context = PresentationContext("ada")
    assert type(context.call_context) is dict
    assert context.call_context == {}
    assert dict(context.shapes) == {}


def test_each_context_built_by_hand_has_a_call_context_of_its_own() -> None:
    """A fresh dict per context, never one shared default every call writes to."""
    assert PresentationContext("ada").call_context is not PresentationContext("ada").call_context


def test_the_call_context_is_the_object_handed_in() -> None:
    """The same dict, not a copy: a presenter, and a nested one handed the
    same context, reuse what an earlier stage of the call put there."""
    shared: dict[str, object] = {"rates": {"EUR": 1}}
    context = PresentationContext("ada", call_context=shared)
    assert context.call_context is shared


def test_the_call_context_and_the_shapes_trail_every_other_field() -> None:
    shared: dict[str, object] = {}
    shapes = MappingProxyType({"fields": ["name"]})
    context = PresentationContext("ada", "row", MappingProxyType({}), shared, shapes)
    assert (context.call_context, context.shapes) == (shared, shapes)
    assert context.call_context is shared


def test_two_contexts_differing_in_call_context_or_shapes_alone_are_equal() -> None:
    one = PresentationContext(
        "ada", "row", call_context={"tenant": "a"}, shapes=MappingProxyType({"fields": ["a"]})
    )
    assert one == PresentationContext("ada", "row")


def test_a_context_carrying_a_call_context_and_shapes_is_hashable() -> None:
    """Neither a dict nor a list a caller sent as a shape can be hashed, so
    both stay out of the hash, as ``ambient`` does."""
    context = PresentationContext(
        "ada", "row", call_context={"tenant": "a"}, shapes=MappingProxyType({"fields": ["a"]})
    )
    assert hash(context) == hash(PresentationContext("ada", "row"))
