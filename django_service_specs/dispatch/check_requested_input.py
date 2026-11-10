from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.parameters.parameters import Parameter
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.server_owned_keys import server_owned_keys
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource

_SCALAR_TYPES = frozenset({"string", "number", "integer", "boolean"})
"""The scalar types a question may ask for: the narrowest renderer's. An MCP
elicitation form takes top-level fields of these four and an array of enum
values, and nothing else; its server refuses any other shape for every caller,
so a question it cannot ask is one no route may ask."""

_ANSWERS: dict[str, frozenset[str]] = {
    "string": frozenset({"string"}),
    "integer": frozenset({"integer"}),
    "number": frozenset({"integer", "number"}),
    "boolean": frozenset({"boolean"}),
    "any": _SCALAR_TYPES,
}
"""For each parameter type, the scalar types every answer of which its shape
check takes. Any value an ``integer`` question admits is a number, so it may
fill a ``number``; a ``number`` question admits ``5.5``, which no ``integer``
takes. ``object`` and ``file`` take no scalar, and ``array`` takes only the
list, which is read on its own."""


def check_requested_input(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    schema: Mapping[str, Any] | None,
    *,
    pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS,
    call_context: dict[str, Any] | None = None,
) -> None:
    """Refuse an ``AdditionalInputRequired.schema`` no route can ask or hear answered."""
    spec = kernel_spec(spec)
    if schema is None:
        return
    if not isinstance(schema, Mapping):
        raise ImproperlyConfigured(
            f"AdditionalInputRequired.schema is a {type(schema).__name__}, not a mapping of "
            "argument names to schema fragments."
        )
    parameters = spec.parameters(call_context=call_context)
    owned = server_owned_keys(spec, pool_seeds=pool_seeds, call_context=call_context)
    for name, fragment in schema.items():
        declared = parameters.get(name)
        if declared is None:
            raise ImproperlyConfigured(_undeclared(spec, name))
        if name in owned:
            raise ImproperlyConfigured(
                f"AdditionalInputRequired asked for {name!r}, and a provider or a pool seed "
                "fills it, so the caller's answer would be dropped: ask under a key the "
                "server leaves to the caller."
            )
        if not isinstance(fragment, dict):
            raise ImproperlyConfigured(
                f"AdditionalInputRequired asked for {name!r} with {type(fragment).__name__} "
                "instead of a schema object; each value is a JSON Schema fragment, "
                'such as {"type": "boolean"}.'
            )
        asked = fragment.get("type")
        if not _renderable(asked, fragment.get("items")):
            raise ImproperlyConfigured(
                f"AdditionalInputRequired asked for {name!r} with type {asked!r}, which not every "
                f"transport can render: a question takes {', '.join(sorted(_SCALAR_TYPES))} or an "
                "array of enum values, so flatten anything else into separate arguments."
            )
        if not _agrees(declared, fragment):
            raise ImproperlyConfigured(
                f"AdditionalInputRequired asked for {name!r} as {asked!r}, and the parameter is "
                f"declared {_described(declared)}, so the answering call would fail "
                "the shape check."
            )


def _undeclared(spec: ServiceSpec | SelectorSpec, name: str) -> str:
    """The refusal of a key no top-level parameter declares, for a ``many`` spec."""
    message = (
        f"AdditionalInputRequired asked for {name!r}, and the operation declares no top-level "
        "parameter of that name, so no call could carry the answer."
    )
    if isinstance(spec, ServiceSpec) and spec.many:
        message += (
            " On a many spec the top level is the list and the spec's reads: declare a value "
            "asked once for the call in reads."
        )
    return message


def _renderable(asked: Any, items: Any) -> bool:
    """Whether the narrowest renderer takes a fragment of type ``asked`` with ``items``."""
    if not isinstance(asked, str):
        return False
    if asked in _SCALAR_TYPES:
        return True
    return (
        asked == "array"
        and isinstance(items, dict)
        and (isinstance(items.get("enum"), list) or isinstance(items.get("anyOf"), list))
    )


def _agrees(declared: Parameter, fragment: dict[str, Any]) -> bool:
    """Whether every answer to a renderable ``fragment`` is of a type ``declared`` takes."""
    asked = fragment["type"]
    if asked != "array":
        return asked in _answers(declared.type, declared.format)
    if declared.type == "any":
        return True
    if declared.type != "array":
        return False
    element = "any" if declared.items is None else declared.items
    if not isinstance(element, str):
        return False
    value_type = fragment["items"].get("type", "string")
    return isinstance(value_type, str) and value_type in _answers(element, declared.format)


def _answers(declared_type: str, declared_format: str | None) -> frozenset[str]:
    """The scalar types every answer of which a parameter of this type and format takes."""
    if declared_type == "string" and declared_format == "decimal":
        return _SCALAR_TYPES - {"boolean"}
    return _ANSWERS.get(declared_type, frozenset())


def _described(declared: Parameter) -> str:
    """The declared parameter's type as a refusal names it."""
    if declared.type != "array" or declared.items is None:
        return repr(declared.type)
    element = declared.items if isinstance(declared.items, str) else "object"
    return f"an array of {element!r}"
