from __future__ import annotations

import copy
from typing import Any

from django_service_specs.settings import field_schema_registry
from django_service_specs.types.json_schema_registry import JsonSchemaRegistry


def registered_fragment(
    field_type: type,
    registry: JsonSchemaRegistry | None = None,
    *,
    project_registry: bool = True,
) -> dict[str, Any] | None:
    """The JSON Schema fragment a field of ``field_type`` is declared as, or ``None``.

    ``registry`` is the seat's own rules and answers first, through the whole
    MRO; the registry the ``SERVICE_SPECS_FIELD_SCHEMA_REGISTRY`` setting names
    answers what the seat's does not, read at the call, so ``override_settings``
    reaches a seat built before it. ``project_registry=False`` is a seat that
    opts out of the project's rules; an empty ``registry`` adds no rule of its
    own and still reads the project's. ``None`` leaves the field to the seat's
    own table. The fragment is a copy, the caller's to change.
    """
    fragment = _rule(registry, field_type)
    if fragment is None and project_registry:
        fragment = _rule(field_schema_registry(), field_type)
    return None if fragment is None else copy.deepcopy(fragment)


def _rule(registry: JsonSchemaRegistry | None, field_type: type) -> dict[str, Any] | None:
    """The rule of the most specific class in ``field_type``'s MRO, the first for one class."""
    if registry is None:
        return None
    for cls in field_type.__mro__:
        for rule_type, fragment in registry.fields:
            if rule_type is cls:
                return fragment
    return None
