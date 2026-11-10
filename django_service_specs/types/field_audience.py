from __future__ import annotations

from enum import Enum


class FieldAudience(str, Enum):
    """Whether an output field is content, a name, a handle, or plumbing."""

    CONTENT = "content"
    """The default: ordinary data, shown to every consumer."""

    LABEL = "label"
    """The field that names this record for a human. At most one per output, and
    two are refused when the output is read into a projection."""

    HANDLE = "handle"
    """An opaque identifier. Passed to other tools, never read out to a user, and
    never re-spelled by a choice's display - a handle is somebody else's input."""

    HIDDEN = "hidden"
    """Plumbing. Dropped from the projected payload and from the projected schema."""
