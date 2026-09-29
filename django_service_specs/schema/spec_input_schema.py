"""``spec_input_schema`` - the JSON Schema of what a spec takes."""

from __future__ import annotations

from typing import Any

from django_service_specs.schema.parameters_schema import parameters_schema
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.validation.unknown_arguments import UnknownArguments


def spec_input_schema(
    spec: ServiceSpec | SelectorSpec,
    *,
    unknown_arguments: UnknownArguments = UnknownArguments.REJECT,
) -> dict[str, Any]:
    """[`parameters_schema`][django_service_specs.schema.parameters_schema.parameters_schema] over ``spec.parameters()``.

    The whole argument set dispatch checks: a selector spec's ``reads``, or a
    service spec's target selector's ``reads`` followed by its Validator's
    parameters. Pass the ``unknown_arguments`` the transport dispatches with,
    because the schema closes the argument set exactly when dispatch does.

    Read on every call, as ``parameters()`` is, so a Validator reading a
    model-backed declaration is asked only once the app registry is ready.
    """
    return parameters_schema(spec.parameters(), unknown_arguments=unknown_arguments)
