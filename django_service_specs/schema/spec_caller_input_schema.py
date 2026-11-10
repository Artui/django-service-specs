from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from django_service_specs.dispatch.provider_reached import provider_reached
from django_service_specs.dispatch.utils import reach
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.schema.spec_input_schema import spec_input_schema
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.server_owned_keys import server_owned_keys
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.types.server_arguments import ServerArguments
from django_service_specs.types.unknown_arguments import UnknownArguments
from django_service_specs.validation.validator import Validator
from django_service_specs.validation.validator_parameters import validator_parameters


def spec_caller_input_schema(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    *,
    pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS,
    server_arguments: ServerArguments | None = None,
    unknown_arguments: UnknownArguments = UnknownArguments.REJECT,
    call_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """What a caller is asked to send ``spec``: ``spec_input_schema`` less server answers."""
    spec = kernel_spec(spec)
    schema = spec_input_schema(spec, unknown_arguments=unknown_arguments, call_context=call_context)
    withheld = server_owned_keys(spec, pool_seeds=pool_seeds, call_context=call_context)
    if isinstance(spec, ServiceSpec) and spec.many:
        validator = cast(Validator, spec.validator)
        fields = validator_parameters(validator, call_context=call_context)
        owned, reached = reach(spec.input_data, fields)
        the_list = schema["properties"][spec.many_argument]
        the_list["items"] = _asked(the_list["items"], withheld=owned, relaxed=reached)
        withheld -= {spec.many_argument}
    if server_arguments is not None:
        withheld |= server_arguments.names()
    relaxed = provider_reached(spec, call_context=call_context)
    return _asked(schema, withheld=withheld, relaxed=relaxed)


def _asked(
    node: Mapping[str, Any], *, withheld: frozenset[str], relaxed: frozenset[str]
) -> dict[str, Any]:
    """``node`` less ``withheld``, with ``relaxed`` offered and not required."""
    asked = {key: value for key, value in node.items() if key != "required"}
    asked["properties"] = {
        name: fragment for name, fragment in node["properties"].items() if name not in withheld
    }
    required = [name for name in node.get("required", ()) if name not in withheld | relaxed]
    if required:
        asked["required"] = required
    return asked
