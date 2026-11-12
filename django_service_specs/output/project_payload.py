from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.output.audience_projection import AudienceProjection
from django_service_specs.types.field_audience import FieldAudience


def project_payload(payload: Any, projection: AudienceProjection) -> Any:
    """Drop plumbing, speak choice displays and format values, at any depth.

    Three changes, each driven by the declaration that shapes the schema in
    [`annotate_output_schema`][django_service_specs.output.annotate_output_schema.annotate_output_schema],
    so the two cannot disagree:

    - fields marked ``HIDDEN`` are **removed**. Removed rather than moved under
      some reserved key: a payload a model reads is read in full either way, so
      moving a field costs its keys again and hides nothing. What an agent must
      never use should not be there.
    - a field's choice value is replaced by its display, so a person is not
      read ``PENDING_REVIEW``. **Not** on a ``HANDLE``, which another tool
      takes as input. An array of choices is substituted member by member
      rather than looked up whole.
    - a field whose marking carries a
      [`ValueFormatter`][django_service_specs.types.value_formatter.ValueFormatter]
      is rendered through it: a date-time read as a local date-time rather
      than raw ISO-8601, an amount with its currency. It wins over the choice
      display, being the transform an author wrote by hand, and over a nested
      output's projection. Also **not** on a ``HANDLE``, for the same reason,
      and a null is never formatted.

    A payload that is neither an object nor a list of them is returned as it
    is, and so is every key the projection has nothing to say about, including
    one a transport added beside the declared fields.

    Apply this where a payload becomes an agent's **answer**, not where it
    feeds the next step of a chain, which still needs the handles. Returns a
    new payload and never modifies ``payload``.
    """
    if projection.is_empty():
        return payload
    return _project(payload, projection)


def _project(payload: Any, projection: AudienceProjection) -> Any:
    # Declared beats derived, deliberately, not by whichever branch is reached first.
    if isinstance(payload, list):
        return [_project(item, projection) for item in payload]
    if not isinstance(payload, Mapping):
        return payload
    projected: dict[str, Any] = {}
    for key, value in payload.items():
        audience = projection.audience(key)
        if audience is FieldAudience.HIDDEN:
            continue
        formatter = projection.formatter(key)
        child = projection.nested.get(key)
        if formatter is not None:
            projected[key] = formatter.apply(value)
        elif child is not None:
            projected[key] = _project(value, child)
        elif audience is not FieldAudience.HANDLE and key in projection.choice_labels:
            projected[key] = _spoken(value, projection.choice_labels[key])
        else:
            projected[key] = value
    return projected


def _spoken(value: Any, labels: Mapping[Any, str]) -> Any:
    """The display for a presented choice, or the value unchanged."""
    if isinstance(value, list | tuple | set | frozenset):
        return [labels.get(member, member) for member in value]
    return labels.get(value, value)
