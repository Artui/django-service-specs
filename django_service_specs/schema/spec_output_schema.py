from __future__ import annotations

from typing import Any

from django_service_specs.affordances.utils import (
    AFFORDANCES_KEY,
    affordance_schema,
    rendered_affordances,
)
from django_service_specs.output.annotate_output_schema import annotate_output_schema
from django_service_specs.output.audience_projection import AudienceProjection
from django_service_specs.schema.can_present_nothing import can_present_nothing
from django_service_specs.schema.output_schema import output_schema
from django_service_specs.schema.utils import allow_null
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.types.selector_kind import SelectorKind


def spec_output_schema(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    *,
    paginate: bool = False,
    projection: AudienceProjection | None = None,
    handle_description: str | None = None,
) -> dict[str, Any] | None:
    """The JSON Schema of what ``present`` returns for ``spec``."""
    compiled = kernel_spec(spec)
    output = compiled.output()
    if output is None:
        return None
    item: dict[str, Any] = output_schema(output)
    if projection is not None:
        item = (
            annotate_output_schema(item, projection, handle_description=handle_description) or item
        )
    if compiled.shapes:
        item = _unrequired(item)
    affordances = rendered_affordances(compiled)
    if affordances is not None:
        item = {
            **item,
            "properties": {
                **item.get("properties", {}),
                AFFORDANCES_KEY: affordance_schema(affordances),
            },
            "required": [*item.get("required", []), AFFORDANCES_KEY],
        }
    if isinstance(compiled, SelectorSpec):
        kind = compiled.kind
    elif compiled.output_selector_spec is not None:
        kind = compiled.output_selector_spec.kind
    else:
        lists = compiled.many or compiled.returns_many
        whole: dict[str, Any] = {"type": "array", "items": item} if lists else item
        return allow_null(whole) if can_present_nothing(compiled) else whole
    if kind is SelectorKind.LIST:
        array: dict[str, Any] = {"type": "array", "items": item}
        return _paged(array) if paginate else array
    return allow_null(item) if can_present_nothing(compiled) else item


def _unrequired(node: dict[str, Any]) -> dict[str, Any]:
    """``node`` and every object and array element under it, with no ``required``."""
    cut = {key: value for key, value in node.items() if key != "required"}
    if "properties" in node:
        cut["properties"] = {name: _unrequired(value) for name, value in node["properties"].items()}
    if "items" in node:
        cut["items"] = _unrequired(node["items"])
    return cut


def _paged(array: dict[str, Any]) -> dict[str, Any]:
    """The paging envelope around ``array``, as ``OutputPage.envelope`` writes it."""
    return {
        "type": "object",
        "properties": {
            "items": array,
            "page": {"type": "integer"},
            "totalPages": {"type": "integer"},
            "hasNext": {"type": "boolean"},
        },
        "required": ["items", "page", "totalPages", "hasNext"],
    }
