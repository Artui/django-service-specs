from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.output.audience_projection import AudienceProjection
from django_service_specs.types.field_audience import FieldAudience


def project_payload(payload: Any, projection: AudienceProjection) -> Any:
    """Drop plumbing, speak choice displays and format values, at any depth."""
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
