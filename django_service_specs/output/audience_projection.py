from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.types.field_audience import FieldAudience
from django_service_specs.types.value_formatter import ValueFormatter


@dataclass(frozen=True)
class AudienceProjection:
    """How one operation's output is shaped for an agent audience."""

    fields: Mapping[str, FieldMarking] = field(default_factory=dict)
    """Every explicitly marked field, by name. Unmarked fields are absent."""

    label: str | None = None
    """The field naming this record for a human, if one is marked."""

    choice_labels: Mapping[str, Mapping[Any, str]] = field(default_factory=dict)
    """Per field with choices, the ``{value: display}`` pairs whose display
    differs from the value. Absent for a field whose displays only repeat its
    values."""

    nested: Mapping[str, AudienceProjection] = field(default_factory=dict)
    """Child projections, by field name, for a nested object and for the
    objects of an array."""

    def is_empty(self) -> bool:
        """True when applying this projection would change nothing."""
        return not (
            self.fields
            or self.label
            or self.choice_labels
            or any(not child.is_empty() for child in self.nested.values())
        )

    def audience(self, name: str) -> FieldAudience:
        """The audience declared for ``name``, defaulting to ``CONTENT``."""
        marking = self.fields.get(name)
        return marking.audience if marking is not None else FieldAudience.CONTENT

    def formatter(self, name: str) -> ValueFormatter | None:
        """The formatter that applies to ``name``, or ``None``."""
        marking = self.fields.get(name)
        if marking is None or marking.audience is FieldAudience.HANDLE:
            return None
        return marking.formatter
