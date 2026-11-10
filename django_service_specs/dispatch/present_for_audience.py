from __future__ import annotations

from typing import Any

from django_service_specs.dispatch.audience_projection_for_spec import audience_projection_for_spec
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.present import present
from django_service_specs.output.audience_projection import AudienceProjection
from django_service_specs.output.project_payload import project_payload
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource


def present_for_audience(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    result: DispatchResult,
    *,
    projection: AudienceProjection | None = None,
) -> Any:
    """[`present`][django_service_specs.dispatch.present.present] plus the agent projection."""
    spec = kernel_spec(spec)
    payload: Any = present(spec, result)
    if projection is None:
        projection = audience_projection_for_spec(spec)
    return project_payload(payload, projection)
