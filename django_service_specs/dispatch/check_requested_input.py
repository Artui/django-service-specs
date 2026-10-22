"""``check_requested_input`` - whether every transport can ask what a service asks, and hear the answer."""

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
) -> None:
    """Refuse an ``AdditionalInputRequired.schema`` some route could not ask, or could not hear answered.

    ``schema`` is what a service raised
    [`AdditionalInputRequired`][django_service_specs.services.additional_input_required.AdditionalInputRequired]
    with, read against ``spec``: a transport calls this before it renders the
    question, so a service asks the same question on every route or on none.
    ``None``, a raise that carries no schema, asks nothing and passes.

    It reads the spec's top-level ``parameters()`` and the schema, runs no
    query and returns nothing. Each key is refused, by name, with
    ``ImproperlyConfigured``, in this order:

    - **A key no top-level parameter declares.** The answer comes back as an
      ordinary argument, so a key the closed argument set refuses could never
      carry it. On a ``many`` spec the top level is the list and the spec's
      ``reads``, so a value asked once for the whole call is a ``reads``
      parameter, and a key declared only inside a row is refused.
    - **A key the server fills**: one a provider the dispatch runs is
      annotated to fill, or a seed ``pool_seeds`` registers - a ``reflected``
      read the seed fills among them - as
      [`server_owned_keys`][django_service_specs.specs.server_owned_keys.server_owned_keys]
      reads them. Dispatch drops the caller's value for such a key, so the
      answer would never reach the service. ``pool_seeds`` is the call's, as
      ``dispatch`` takes it. A top-level Validator field named like a
      registered seed may be asked for, since the answer reaches the
      Validator and ``data``
      (test_server_owned_keys_leaves_such_a_field_out_and_a_service_may_ask_for_it),
      and so may a key a provider may decline or one an untyped provider's
      values reach, whose caller's value stands when the provider declines.
    - **A fragment that is not a schema object**: a ``dict``, as JSON carries
      one.
    - **A shape some transport cannot render.** The narrowest is an MCP
      elicitation form, which takes a ``string``, ``number``, ``integer`` or
      ``boolean``, or an ``array`` whose ``items`` list enum values, untitled
      (``enum``) or titled (``anyOf``). A ``type`` list, an ``object``, a
      fragment naming no type and an array of anything else are refused.
    - **A** ``type`` **the declared parameter does not take**, since the
      answering call would fail the shape check whatever was answered. The
      answer must be of a type the parameter takes: an ``integer`` question
      may fill a ``number`` parameter and not the reverse, any question may
      fill an ``any``, and a number may fill a ``decimal`` string, as
      ``check_arguments`` reads one. An array question fills an ``array``
      whose element takes its values, which are strings unless its ``items``
      name a type, as both of MCP's multi-select shapes are; the rows of a
      ``many`` list are objects, which no list of values fills. The ``type``
      is compared and nothing finer: a ``format``, ``choices`` or a bound the
      parameter declares still checks the answer when it arrives.

    A [`SpecSource`][django_service_specs.specs.spec_source.SpecSource] is
    read as the spec it compiles to.

    Raises:
        ImproperlyConfigured: naming the first key refused, or for a
            ``schema`` that is no mapping at all.
    """
    spec = kernel_spec(spec)
    if schema is None:
        return
    if not isinstance(schema, Mapping):
        raise ImproperlyConfigured(
            f"AdditionalInputRequired.schema is a {type(schema).__name__}, not a mapping of "
            "argument names to schema fragments."
        )
    parameters = spec.parameters()
    owned = server_owned_keys(spec, pool_seeds=pool_seeds)
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
                'instead of a schema object; each value is a JSON Schema fragment, such as {"type": '
                '"boolean"}.'
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
                f"declared {_described(declared)}, so the answering call would fail the shape check."
            )


def _undeclared(spec: ServiceSpec | SelectorSpec, name: str) -> str:
    """The refusal of a key no top-level parameter declares, pointing a ``many`` spec at its reads."""
    message = (
        f"AdditionalInputRequired asked for {name!r}, and the operation declares no top-level "
        "parameter of that name, so no call could carry the answer."
    )
    # Two conjuncts: a selector spec has no ``many`` to read
    # (test_a_selector_spec_is_given_no_many_hint), and a spec that is not
    # ``many`` has no row to confuse with the top level
    # (test_a_key_no_parameter_declares_is_refused).
    if isinstance(spec, ServiceSpec) and spec.many:
        message += (
            " On a many spec the top level is the list and the spec's reads: declare a value "
            "asked once for the call in reads."
        )
    return message


def _renderable(asked: Any, items: Any) -> bool:
    """Whether the narrowest renderer takes a fragment of type ``asked`` with ``items``.

    A ``type`` that is no string, a list among them, is no type here, as it is
    to the MCP server, which would otherwise fail on an unhashable list.
    """
    if not isinstance(asked, str):
        return False
    if asked in _SCALAR_TYPES:
        return True
    # Three conjuncts, the last of two alternatives, each held by its own
    # test: test_an_object_is_refused[with-enum-items] fails without the
    # first, test_an_array_without_enum_items_is_refused[items-not-a-schema-object]
    # without the second, test_an_array_of_enum_values_passes without
    # ``enum`` and test_an_array_of_titled_values_passes without ``anyOf``;
    # [enum-not-a-list] and [any-of-not-a-list] hold each ``list`` test.
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
    # A list with no declared element takes any; a list of rows takes objects,
    # which no list of values fills.
    element = "any" if declared.items is None else declared.items
    if not isinstance(element, str):
        return False
    # Untyped, the values are strings, as in both of MCP's multi-select shapes.
    # Two conjuncts: a ``type`` that is no string names no element type, and
    # test_an_element_type_list_is_refused fails without the first, on an
    # unhashable list rather than a refusal.
    value_type = fragment["items"].get("type", "string")
    return isinstance(value_type, str) and value_type in _answers(element, declared.format)


def _answers(declared_type: str, declared_format: str | None) -> frozenset[str]:
    """The scalar types every answer of which a parameter of this type and format takes."""
    # Two conjuncts: test_an_integer_for_an_array_of_decimal_strings_is_refused
    # fails without the first, since an array's format describes its elements,
    # and [integer-for-string] in TestDisagrees without the second.
    if declared_type == "string" and declared_format == "decimal":
        # ``check_arguments`` takes a JSON number for a decimal, as every
        # decimal validator does.
        return _SCALAR_TYPES - {"boolean"}
    return _ANSWERS.get(declared_type, frozenset())


def _described(declared: Parameter) -> str:
    """The declared parameter's type as a refusal names it."""
    if declared.type != "array" or declared.items is None:
        return repr(declared.type)
    element = declared.items if isinstance(declared.items, str) else "object"
    return f"an array of {element!r}"
