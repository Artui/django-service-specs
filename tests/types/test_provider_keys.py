from __future__ import annotations

from django_service_specs.types.provider_keys import ProviderKeys


def test_it_reads_by_name_and_unpacks_as_a_pair() -> None:
    keys = ProviderKeys(filled=frozenset({"tenant"}), declinable=frozenset({"region"}))
    filled, declinable = keys
    assert (filled, declinable) == (keys.filled, keys.declinable)
    assert keys == (frozenset({"tenant"}), frozenset({"region"}))
