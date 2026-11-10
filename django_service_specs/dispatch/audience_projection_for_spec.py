from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.output.audience_projection import AudienceProjection
from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.output.output import Output
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.types.field_audience import FieldAudience


def audience_projection_for_spec(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    *,
    overrides: Mapping[str, FieldMarking] | None = None,
    name: str | None = None,
) -> AudienceProjection:
    """Resolve the markings on the ``Output`` that ``spec`` presents."""
    output = kernel_spec(spec).output()
    projection = (
        AudienceProjection()
        if output is None
        else _project(output, path="", subject=name or "Output")
    )
    if not overrides:
        return projection
    return _with_overrides(projection, overrides, name=name or "agent projection")


def _project(output: Output, *, path: str, subject: str) -> AudienceProjection:
    """One output's markings, recursing into every child declared as an ``Output``."""
    marked: dict[str, FieldMarking] = {}
    choice_labels: dict[str, dict[Any, str]] = {}
    nested: dict[str, AudienceProjection] = {}
    label: str | None = None
    for field in output:
        if field.marking is not None:
            marked[field.name] = field.marking
            if field.marking.audience is FieldAudience.LABEL:
                if label is not None:
                    where = f"{subject} field {path!r}" if path else subject
                    raise ImproperlyConfigured(
                        f"{where}: both {label!r} and {field.name!r} are marked "
                        "FieldMarking.label(). A record has one name - pick the field an "
                        "agent should call it by."
                    )
                label = field.name
        if field.choices is not None:
            labels = {
                value: str(display)
                for value, display in field.choices
                if str(display) != str(value)
            }
            if labels:
                choice_labels[field.name] = labels
        child = field.fields if field.fields is not None else field.items
        if isinstance(child, Output):
            child_projection = _project(
                child, path=f"{path}.{field.name}" if path else field.name, subject=subject
            )
            if not child_projection.is_empty():
                nested[field.name] = child_projection
    return AudienceProjection(
        fields=marked, label=label, choice_labels=choice_labels, nested=nested
    )


def _with_overrides(
    projection: AudienceProjection, overrides: Mapping[str, FieldMarking], *, name: str
) -> AudienceProjection:
    """The declaration's markings with one mount's overrides layered over them."""
    fields: dict[str, FieldMarking] = {**projection.fields, **overrides}
    labels = [n for n, marking in fields.items() if marking.audience is FieldAudience.LABEL]
    if len(labels) > 1:
        raise ImproperlyConfigured(
            f"{name}: overrides leave {labels!r} all marked as the label. A record has one "
            "name - override the others to something else."
        )
    return AudienceProjection(
        fields=fields,
        label=labels[0] if labels else None,
        choice_labels=projection.choice_labels,
        nested=projection.nested,
    )
