from __future__ import annotations

from enum import Enum


class RefusalFindingKind(str, Enum):
    """What a ``RefusalFinding`` found."""

    UNANSWERED = "unanswered"
    """Nothing in the map answers the refusal: no row, or no call."""

    BARE_BASE = "bare_base"
    """The map answers every refusal under a base and not the base itself.

    It looks complete and is not, since either family base may be raised bare:
    the kernel raises neither itself, but a project's own code may.
    """

    SHADOWED_ROW = "shadowed_row"
    """A table's row never answers, because an earlier row of its own base, or
    of its own class, answers every refusal it names first.

    Reported for a table only: a callable's branch order is code, which the
    transport's own branch coverage reads.
    """


__all__ = ["RefusalFindingKind"]
