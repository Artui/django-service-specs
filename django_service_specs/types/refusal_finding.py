"""``RefusalFinding`` - one thing a transport's refusal map gets wrong."""

from __future__ import annotations

from dataclasses import dataclass

from django_service_specs.types.refusal_finding_kind import RefusalFindingKind


@dataclass(frozen=True)
class RefusalFinding:
    """One finding of
    [`unanswered_refusals`][django_service_specs.dispatch.unanswered_refusals.unanswered_refusals]:
    the refusal it is about, which kind of finding it is, and for a shadowed
    row, the row that shadows it.

    A value, so a transport holds its map with ``== ()`` and allows a gap it
    means by filtering on ``refusal`` or ``kind``, never on the words, which
    ``str()`` gives and which are free to change.

    The classes are typed as any exception rather than as the kernel's two
    families, because a shadowed row may name a transport's own refusal, or a
    catch-all ``Exception`` above it.
    """

    #: The refusal the finding is about. For a shadowed row, the row's class.
    refusal: type[BaseException]
    #: Which of the three findings this is.
    kind: RefusalFindingKind
    #: The earlier row that answers first, for a shadowed row; otherwise ``None``.
    shadowed_by: type[BaseException] | None = None

    def __str__(self) -> str:
        """The finding in a sentence, naming the classes it is about."""
        name = self.refusal.__name__
        if self.kind is RefusalFindingKind.BARE_BASE:
            return (
                f"nothing in the map answers {name} itself, though it answers every "
                f"refusal under it, and {name} may be raised bare"
            )
        if self.kind is RefusalFindingKind.SHADOWED_ROW:
            # Read without a branch: the kind is what says a row shadows it,
            # and a finding built without one says so as ``None``.
            above = getattr(self.shadowed_by, "__name__", None)
            return (
                f"the row for {name} never answers: the row for {above} "
                f"above it answers every {name} first"
            )
        return f"nothing in the map answers {name}"


__all__ = ["RefusalFinding"]
