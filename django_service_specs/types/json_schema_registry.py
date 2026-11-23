from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

_Rule = tuple[type, dict[str, Any]]


@dataclass(frozen=True)
class JsonSchemaRegistry:
    """Rules mapping a field type to the JSON Schema fragment it is declared as.

    A seat that walks fields - the kernel's
    [`FormValidator`][django_service_specs.adapters.forms.form_validator.FormValidator],
    and the serializer seats of django-spec-rest - asks
    [`registered_fragment`][django_service_specs.schema.registered_fragment.registered_fragment]
    for a field's type before its own table, so a rule both describes a type the
    seat has no mapping for and overrides one it has: a ``forms.IntegerField``
    subclass that reads strings is declared a string.

    A field is matched through its class's MRO, so the most specific class with a
    rule wins whatever the order the rules are listed in; two rules for one class
    are answered by the first. The registry imports neither forms nor DRF: a rule
    names any class.

    Immutable: ``extend`` returns a new registry, so there is no shared state to
    leak across callers or tests. ``JsonSchemaRegistry()`` is the empty one:

        registry = JsonSchemaRegistry().extend(
            fields=[(LooseIntegerField, {"type": "string"})],
        )
        validator = FormValidator(OrderForm, json_schema_registry=registry)

    A seat's registry sits in front of the project's, which the
    ``SERVICE_SPECS_FIELD_SCHEMA_REGISTRY`` setting names; see
    [field schema rules](schema.md#field-schema-rules).

    Attributes:
        fields: ``(type, fragment)`` rules, each a class and the JSON Schema a
            field of it is declared as.
    """

    fields: tuple[_Rule, ...] = ()

    def extend(self, *, fields: Sequence[_Rule] = ()) -> JsonSchemaRegistry:
        """A new registry with ``fields`` prepended, so for one class they answer first."""
        return replace(self, fields=tuple(fields) + self.fields)
