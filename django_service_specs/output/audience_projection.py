"""``AudienceProjection`` - an output's field markings, resolved once."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from django_service_specs.output.field_audience import FieldAudience
from django_service_specs.output.field_marking import FieldMarking


@dataclass(frozen=True)
class AudienceProjection:
    """How one operation's output is shaped for an agent audience.

    Read off the [`FieldMarking`][django_service_specs.output.field_marking.FieldMarking]s
    and the choices an [`Output`][django_service_specs.output.output.Output]
    declares, by
    [`audience_projection_for_spec`][django_service_specs.output.audience_projection_for_spec.audience_projection_for_spec].
    Nothing here depends on the value being presented, so a transport builds
    it **once**, where it registers the spec, and passes it to every
    [`render_for_audience`][django_service_specs.dispatch.render_for_audience.render_for_audience]
    and [`spec_output_schema`][django_service_specs.schema.spec_output_schema.spec_output_schema]
    rather than reading the declaration again per call.

    One projection drives both
    [`project_payload`][django_service_specs.output.project_payload.project_payload]
    and [`annotate_output_schema`][django_service_specs.output.annotate_output_schema.annotate_output_schema],
    which is what keeps the advertised schema describing the payload sent.
    """

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
        """True when applying this projection would change nothing.

        The fast path: an unmarked output with no labelled choices anywhere
        costs a caller one boolean rather than a walk of the payload.

        One ``or``-chain, so each term is held by its own case of
        ``test_each_term_alone_makes_it_non_empty``.
        """
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
