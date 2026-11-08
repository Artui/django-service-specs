"""``TRANSPORT_KEY``, the one name every transport stamps a call's context under."""

from __future__ import annotations

from django_service_specs.pool.reserved_pool_seeds import RESERVED_POOL_SEEDS
from django_service_specs.types.transport_key import TRANSPORT_KEY


def test_the_key_keeps_the_spelling_spec_agents_already_publishes() -> None:
    # ``call_context["transport"]`` is public in django-spec-agents' docs, so a
    # consumer reads it without importing this. Renaming the constant's value
    # breaks them silently.
    assert TRANSPORT_KEY == "transport"


def test_the_key_is_not_a_reserved_pool_name() -> None:
    # The owner's call: the key is a convention over the dict, so a seed, a
    # provider's key or an argument may still be named ``transport``.
    assert TRANSPORT_KEY not in RESERVED_POOL_SEEDS
