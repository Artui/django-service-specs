from __future__ import annotations

from dataclasses import dataclass

from django_service_specs.types.field_audience import FieldAudience
from django_service_specs.types.value_formatter import ValueFormatter


@dataclass(frozen=True, slots=True)
class FieldMarking:
    """How one output field is presented to an agent audience."""

    audience: FieldAudience = FieldAudience.CONTENT
    description: str | None = None
    """Audience-facing description, replacing the field's help text for this
    audience only.

    Help text is shared with every human reader, so it cannot say "opaque
    handle, never read this out". This can, without changing a word of what a
    human reader sees.
    """

    formatter: ValueFormatter | None = None
    """How this field's value is rendered for an agent audience, if not verbatim.

    A [`ValueFormatter`][django_service_specs.types.value_formatter.ValueFormatter]
    transforms the value and declares the JSON type it produces, so the
    payload and the schema move together. Unset, the default, changes
    nothing.

    **An explicit formatter wins over the substitution of a choice's
    display**, which is a real collision: a status field can have choices and
    still be something an author wants spelled their own way. Only one
    transform can apply, and the one written by hand is the one that was asked
    for; a derived default losing to an explicit declaration is the ordinary
    direction.

    **``HANDLE`` suppresses it**, exactly as it suppresses choice
    substitution: a handle is another tool's input, and a formatted machine
    identifier is a broken one. Declaring both is honoured as ``HANDLE`` and
    the formatter never runs. A field a second tool takes as input therefore
    wants [`handle`][django_service_specs.output.field_marking.FieldMarking.handle],
    or that tool receives a display string its own input schema rejects.
    """

    @classmethod
    def handle(cls, description: str | None = None) -> FieldMarking:
        """An opaque identifier: passed to other tools, never spoken to a user."""
        return cls(FieldAudience.HANDLE, description)

    @classmethod
    def hidden(cls) -> FieldMarking:
        """Plumbing: dropped from the projected payload and the projected schema."""
        return cls(FieldAudience.HIDDEN)

    @classmethod
    def label(cls, description: str | None = None) -> FieldMarking:
        """The field that names this record for a human."""
        return cls(FieldAudience.LABEL, description)

    @classmethod
    def formatted(cls, formatter: ValueFormatter, description: str | None = None) -> FieldMarking:
        """Ordinary content, rendered through ``formatter``."""
        return cls(FieldAudience.CONTENT, description, formatter)

    @classmethod
    def timestamp(cls, fmt: str | None = None, description: str | None = None) -> FieldMarking:
        """A date-time read as a formatted local string rather than raw ISO-8601."""
        return cls(FieldAudience.CONTENT, description, ValueFormatter.timestamp(fmt))
