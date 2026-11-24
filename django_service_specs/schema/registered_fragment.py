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

    The most specific class in ``field_type``'s MRO with a rule in either
    registry wins; for one class, ``registry``, the seat's own rules, answers
    before the registry the ``SERVICE_SPECS_FIELD_SCHEMA_REGISTRY`` setting
    names, read at the call, so ``override_settings`` reaches a seat built
    before it. ``project_registry=False`` is a seat that opts out of the
    project's rules; an empty ``registry`` adds no rule of its own and still
    reads the project's. ``None`` leaves the field to the seat's
    own table. The fragment is a copy, the caller's to change.
    """
    registries = [registry, field_schema_registry() if project_registry else None]
    for cls in field_type.__mro__:
        for rules in registries:
            fragment = None if rules is None else _rule(rules, cls)
            if fragment is not None:
                return copy.deepcopy(fragment)
    return None


def _rule(registry: JsonSchemaRegistry, cls: type) -> dict[str, Any] | None:
    """The first rule ``registry`` lists for exactly ``cls``."""
    return next((fragment for rule_type, fragment in registry.fields if rule_type is cls), None)
