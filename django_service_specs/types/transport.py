"""``Transport`` - the family's known names for the transport building a call's context."""

from __future__ import annotations

from enum import Enum


class Transport(str, Enum):
    """The name each of the family's transports stamps under ``TRANSPORT_KEY``.

    One value per package, and the package that builds the call's context stamps
    its own: an MCP call that django-spec-agents proxies in process reads ``MCP``,
    because django-spec-mcp's handler builds that context. Each package stamps from
    the release that adopts the key.

    Not a closed set. A third-party transport stamps its own string, so read a
    stamp by comparing it to a member rather than converting it to one, which
    raises for a string that is not listed here.

    Inheriting from ``str`` makes a member equal to its plain string, the form a
    transport stamps with ``.value``. ``str()`` of a member is its qualified name
    rather than its value, which is why a stamp is never the member itself.
    """

    REST = "rest"
    HTML = "html"
    MCP = "mcp"
    AGENT = "agent"
    CLI = "cli"
