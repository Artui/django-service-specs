"""``audience_projection_for_spec`` - a spec's output markings, resolved once."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.output.audience_projection import AudienceProjection
from django_service_specs.output.field_audience import FieldAudience
from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.output.output import Output

if TYPE_CHECKING:
    # Annotation-only: ``specs/`` imports ``output/`` for the presenter and the
    # ``Output`` it declares, and this reads only ``spec.output()``.
    from django_service_specs.specs.selector_spec import SelectorSpec
    from django_service_specs.specs.service_spec import ServiceSpec


def audience_projection_for_spec(
    spec: ServiceSpec | SelectorSpec,
    *,
    overrides: Mapping[str, FieldMarking] | None = None,
    name: str | None = None,
) -> AudienceProjection:
    """Resolve the markings on the [`Output`][django_service_specs.output.output.Output] ``spec`` presents.

    The output is ``spec.output()``: a selector spec's presenter's, or a
    service spec's own presenter's, or its output selector's when it declares
    none. A transport that registers its tools up front calls this once per
    spec and hands the result to
    [`render_for_audience`][django_service_specs.dispatch.render_for_audience.render_for_audience]
    and [`spec_output_schema`][django_service_specs.schema.spec_output_schema.spec_output_schema],
    so the payload it sends and the schema it advertises are projected by one
    declaration.

    Each [`OutputField`][django_service_specs.output.output_field.OutputField]
    contributes its ``marking``, its ``choices`` whose display differs from the
    value, and, for an object's ``fields`` or an array's ``items`` declared as
    an ``Output``, a child projection when the child has anything to project.
    A spec with no output yields an empty projection rather than an error:
    there is nothing to mark up.

    ``overrides`` layers a mount's own markings over the declaration's, for the
    one case the declaration cannot express: a mount that needs what its
    sibling hides. The declaration stays authoritative, and an override is the
    exception rather than a second place to declare an audience. Only the
    top-level markings and the label move; the choices and the children come
    from the declaration. ``name`` identifies the mount in the refusal below.

    Raises:
        django.core.exceptions.ImproperlyConfigured: Two fields of one output
            are both marked ``LABEL``, whether the declaration says so or an
            override does. A record has one name, and picking one silently
            would name it by whichever came first.
    """
    output = spec.output()
    projection = AudienceProjection() if output is None else _project(output, path="")
    if not overrides:
        return projection
    return _with_overrides(projection, overrides, name=name or "agent projection")


def _project(output: Output, *, path: str) -> AudienceProjection:
    """One output's markings, recursing into every child declared as an ``Output``.

    ``path`` is the dotted field path of a child, empty at the top, so a
    refusal names the output it is about.
    """
    marked: dict[str, FieldMarking] = {}
    choice_labels: dict[str, dict[Any, str]] = {}
    nested: dict[str, AudienceProjection] = {}
    label: str | None = None
    for field in output:
        if field.marking is not None:
            marked[field.name] = field.marking
            if field.marking.audience is FieldAudience.LABEL:
                if label is not None:
                    where = f"Output field {path!r}" if path else "Output"
                    raise ImproperlyConfigured(
                        f"{where}: both {label!r} and {field.name!r} are marked "
                        "FieldMarking.label(). A record has one name - pick the field an "
                        "agent should call it by."
                    )
                label = field.name
        if field.choices is not None:
            # ``str()`` for a lazy translation, read in the language active
            # when the projection is built, as the schema's titles are.
            labels = {
                value: str(display)
                for value, display in field.choices
                if str(display) != str(value)
            }
            if labels:
                choice_labels[field.name] = labels
        # An object's ``fields`` and an array's ``items`` both put an ``Output``
        # one level down, and the schema describes both. Missing either here
        # fails open: a hidden field inside the child would survive.
        child = field.fields if field.fields is not None else field.items
        if isinstance(child, Output):
            child_projection = _project(child, path=f"{path}.{field.name}" if path else field.name)
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
