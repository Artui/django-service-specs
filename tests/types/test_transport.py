"""``Transport``, the family's known transports: one value per package that builds a context."""

from __future__ import annotations

import json

from django_service_specs.types.transport import Transport


def test_the_known_values_are_one_per_package() -> None:
    assert {member.value for member in Transport} == {"rest", "html", "mcp", "agent", "cli"}


def test_a_member_compares_and_hashes_as_the_plain_string_a_transport_stamps() -> None:
    # A stamp is ``.value``, so a stage comparing against a member has to agree
    # with the plain string, in either order and as a key.
    assert Transport.MCP == "mcp"
    assert Transport.MCP == "mcp"
    assert {Transport.MCP: "found"}["mcp"] == "found"


def test_a_stamp_is_a_plain_string_that_serializes_as_itself() -> None:
    stamp = Transport.AGENT.value

    assert type(stamp) is str
    assert json.dumps({"transport": stamp}) == '{"transport": "agent"}'
