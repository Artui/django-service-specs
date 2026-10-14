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
