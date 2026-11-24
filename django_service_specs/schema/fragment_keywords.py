from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.adapters.utils import shared_scalar_type
from django_service_specs.output.output import OutputField
from django_service_specs.parameters.parameters import Parameter

_JSON_TYPES: Final = frozenset({"string", "integer", "number", "boolean", "array", "object"})

# The keywords each declaration spells beyond type, format, enum and items, with its field.
_PARAMETER_FIELDS: Final = (
    ("minimum", "minimum"),
    ("maximum", "maximum"),
    ("minItems", "min_length"),
    ("maxItems", "max_length"),
    ("description", "help"),
)
_OUTPUT_FIELDS: Final = (("title", "label"),)


def fragment_keywords(fragment: Mapping[str, Any], *, output: bool = False) -> dict[str, Any]:
    """A registered fragment as the keywords of a ``Parameter``, or of an ``OutputField``.

    What the declaration can state is kept, and the rest is dropped by the
    declaration's own refusal: ``type`` (``"any"`` where it names no JSON type,
    or a ``[type, "null"]`` pair as the type and ``nullable``), ``format``,
    ``enum`` as ``choices``, a typed ``items``, a parameter's bounds and
    ``description`` as ``help``, an output field's ``title`` as ``label``, and
    any other keyword as ``json_schema_extra``. The result always has ``type``.
    """
    declared: dict[str, Any] = {}
    kind = fragment.get("type")
    if isinstance(kind, list) and "null" in kind and len(kind) == 2:
        declared["nullable"] = True
        kind = next(member for member in kind if member != "null")
    enum = fragment.get("enum")
    if kind is None and isinstance(enum, list):
        kind = shared_scalar_type(tuple(enum))
    declared["type"] = kind if _named(kind) else "any"
    stated: list[tuple[str, Any]] = []
    items = fragment.get("items")
    if isinstance(items, Mapping) and items.keys() == {"type"} and _named(items["type"]):
        stated.append(("items", items["type"]))
    if isinstance(fragment.get("format"), str):
        stated.append(("format", fragment["format"]))
    if isinstance(enum, list):
        choices = tuple((value, str(value)) for value in enum) if output else tuple(enum)
        stated.append(("choices", choices))
    keywords = _OUTPUT_FIELDS if output else _PARAMETER_FIELDS
    stated.extend((name, fragment[keyword]) for keyword, name in keywords if keyword in fragment)
    declaration = OutputField if output else Parameter
    for name, value in stated:
        if _states(declaration, {**declared, name: value}):
            declared[name] = value
    extra = {
        key: value
        for key, value in fragment.items()
        if _states(declaration, {**declared, "json_schema_extra": {key: value}})
    }
    if extra:
        declared["json_schema_extra"] = extra
    return declared


def _states(declaration: type[Parameter] | type[OutputField], keywords: dict[str, Any]) -> bool:
    """Whether the kernel builds ``declaration`` from ``keywords``: its own refusal is the rule."""
    try:
        declaration("registered", **keywords)
    except ImproperlyConfigured:
        return False
    return True


def _named(value: Any) -> bool:
    """Whether ``value`` names a JSON type, which a list or mapping never does."""
    return isinstance(value, str) and value in _JSON_TYPES
