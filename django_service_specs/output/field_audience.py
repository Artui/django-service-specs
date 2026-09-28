"""``FieldAudience`` - who an output field is written for."""

from __future__ import annotations

from enum import Enum


class FieldAudience(str, Enum):
    """Whether an output field is content, a name, a handle, or plumbing.

    An operation's output is often read by more than one kind of consumer: a
    frontend or a command that decides its own presentation, and a model that
    will read the payload aloud unless told otherwise. The two want different
    subsets of the same fields, and the difference is not a transport
    difference - an MCP server and an in-process toolset want the same thing as
    each other and something different from a browser.

    So the axis this names is **audience**, not protocol. Declared per field
    through [`FieldMarking`][django_service_specs.output.field_marking.FieldMarking],
    on the field's [`OutputField`][django_service_specs.output.output_field.OutputField].

    Inheriting from ``str`` keeps the value JSON-serializable and print-friendly
    while still behaving as a proper enum for ``is`` / ``==``.
    """

    CONTENT = "content"
    """The default: ordinary data, shown to every consumer."""

    LABEL = "label"
    """The field that names this record for a human. At most one per output."""

    HANDLE = "handle"
    """An opaque identifier. Passed to other tools, never read out to a user, and
    never re-spelled by a choice's display - a handle is somebody else's input."""

    HIDDEN = "hidden"
    """Plumbing. Dropped from what an audience projection shows."""
