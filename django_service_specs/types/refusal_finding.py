from __future__ import annotations

from dataclasses import dataclass

from django_service_specs.types.refusal_finding_kind import RefusalFindingKind


@dataclass(frozen=True)
class RefusalFinding:
    """One finding of ``unanswered_refusals``: the refusal, its kind, and any shadowing row."""

    refusal: type[BaseException]
    kind: RefusalFindingKind
    shadowed_by: type[BaseException] | None = None

    def __post_init__(self) -> None:
        """Refuse a finding whose row above and kind disagree."""
        if (self.kind is RefusalFindingKind.SHADOWED_ROW) != (self.shadowed_by is not None):
            raise ValueError(
                "A refusal finding names the row above it exactly when it is a "
                f"shadowed row; got kind {self.kind.value!r} and row above {self.shadowed_by!r}."
            )

    def __str__(self) -> str:
        """The finding in a sentence, naming the classes it is about."""
        name = self.refusal.__name__
        if self.kind is RefusalFindingKind.BARE_BASE:
            return (
                f"nothing in the map answers {name} itself, though it answers every "
                f"refusal under it, and {name} may be raised bare"
            )
        if self.kind is RefusalFindingKind.SHADOWED_ROW:
            above = getattr(self.shadowed_by, "__name__", None)
            return (
                f"the row for {name} never answers: the row for {above} "
                f"above it answers every {name} first"
            )
        return f"nothing in the map answers {name}"


__all__ = ["RefusalFinding"]
