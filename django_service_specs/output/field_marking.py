"""``FieldMarking`` - how one output field is presented to an agent audience."""

from __future__ import annotations

from dataclasses import dataclass

from django_service_specs.output.field_audience import FieldAudience


@dataclass(frozen=True, slots=True)
class FieldMarking:
    """How one output field is presented to an agent audience.

    Carried on the [`OutputField`][django_service_specs.output.output_field.OutputField]
    it marks, so it belongs to the declaration of what an operation returns
    rather than to whichever library rendered it. That is what lets a
    transport's projection for an audience work over a dataclass, a pydantic
    model and a DRF serializer alike: each adapter reads its own library's
    declaration into ``Output``, marking included, and the projection reads
    only ``Output``. The kernel carries the marking and applies none of it.

    The marking lives on the **field**, not in a list beside the output. That is
    what lets it travel into a nested output with no hoisting rule, and what
    stops a rename from silently desyncing it from a name the parent maintains.
    """

    audience: FieldAudience = FieldAudience.CONTENT
    description: str | None = None
    """Audience-facing description, replacing the field's help text for this
    audience only.

    Help text is shared with every human reader, so it cannot say "opaque
    handle, never read this out". This can, without changing a word of what a
    human reader sees.
    """

    @classmethod
    def handle(cls, description: str | None = None) -> FieldMarking:
        """An opaque identifier: passed to other tools, never spoken to a user."""
        return cls(FieldAudience.HANDLE, description)

    @classmethod
    def hidden(cls) -> FieldMarking:
        """Plumbing: dropped from the projected payload."""
        return cls(FieldAudience.HIDDEN)

    @classmethod
    def label(cls, description: str | None = None) -> FieldMarking:
        """The field that names this record for a human."""
        return cls(FieldAudience.LABEL, description)
