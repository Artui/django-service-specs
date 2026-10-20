"""``RefusalFindingKind`` - which of three ways a refusal map falls short."""

from __future__ import annotations

from enum import Enum


class RefusalFindingKind(str, Enum):
    """What a [`RefusalFinding`][django_service_specs.types.refusal_finding.RefusalFinding] found.

    The thing a transport filters by when it allows a gap on purpose, beside
    the refusal's class, rather than by a finding's words, which stay free to
    change.

    Inheriting from ``str`` keeps the value JSON-serializable and lets a caller
    compare against the plain string, matching
    [`SelectorKind`][django_service_specs.types.selector_kind.SelectorKind].
    """

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
