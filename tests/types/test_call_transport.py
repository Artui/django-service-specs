"""``call_transport``, which hands back what a transport stamped and invents nothing."""

from __future__ import annotations

from types import MappingProxyType

from django_service_specs.types.call_transport import call_transport
from django_service_specs.types.transport import Transport
from django_service_specs.types.transport_key import TRANSPORT_KEY


def test_it_returns_a_known_transport_s_stamp() -> None:
    assert call_transport({TRANSPORT_KEY: Transport.REST.value}) == Transport.REST


def test_it_returns_a_third_party_transport_s_own_string_unconverted() -> None:
    # The known values are not a closed set: converting to ``Transport`` here
    # would raise for a stamp the docs say is allowed.
    assert call_transport({TRANSPORT_KEY: "worker"}) == "worker"


def test_a_missing_key_reads_as_none() -> None:
    assert call_transport({"request": object()}) is None


def test_a_context_outside_a_call_reads_as_none() -> None:
    # A Validator's ``parameters(call_context=None)`` is handed ``None`` on every
    # ask outside a call, so the reader answers rather than raises there.
    assert call_transport(None) is None


def test_it_reads_any_mapping_and_writes_nothing() -> None:
    assert call_transport(MappingProxyType({TRANSPORT_KEY: "cli"})) == "cli"
