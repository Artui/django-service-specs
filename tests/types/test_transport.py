"""``Transport``, the family's known transports: one value per package that builds a context."""

from __future__ import annotations

import json

import pytest

from django_service_specs.types.transport import Transport


def test_the_known_values_are_one_per_package() -> None:
    # Each name to its value, since nothing else pins these: ``Transport`` is held
    # out of the drfs surface table, and a swap would keep the set of values whole.
    assert {member.name: member.value for member in Transport} == {
        "REST": "rest",
        "HTML": "html",
        "MCP": "mcp",
        "AGENT": "agent",
        "CLI": "cli",
    }


def test_a_member_compares_and_hashes_as_the_plain_string_a_transport_stamps() -> None:
    # A stamp is ``.value``, so a stage comparing against a member has to agree
    # with the plain string, and as a key.
    assert Transport.MCP == "mcp"
    assert {Transport.MCP: "found"}["mcp"] == "found"


def test_a_stamp_is_a_plain_string_that_serializes_as_itself() -> None:
    stamp = Transport.AGENT.value

    assert type(stamp) is str
    assert json.dumps({"transport": stamp}) == '{"transport": "agent"}'


def test_str_of_a_member_is_its_qualified_name_rather_than_the_stamp() -> None:
    # Why the guide says to stamp ``.value``: ``str()`` of a member is not the string.
    assert str(Transport.AGENT) == "Transport.AGENT"


def test_a_string_outside_the_known_values_does_not_convert() -> None:
    # Why the guide says to compare a stamp rather than convert it: the set is
    # not closed, and a third-party transport's string is not a member.
    with pytest.raises(ValueError, match="worker"):
        Transport("worker")
