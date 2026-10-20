"""``spec_input_schema`` - the JSON Schema of what a spec takes."""

from __future__ import annotations

from typing import Any

from django_service_specs.dispatch.relax_partial import relax_partial
from django_service_specs.schema.parameters_schema import parameters_schema
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.types.unknown_arguments import UnknownArguments


def spec_input_schema(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    *,
    unknown_arguments: UnknownArguments = UnknownArguments.REJECT,
) -> dict[str, Any]:
    """[`parameters_schema`][django_service_specs.schema.parameters_schema.parameters_schema] over ``spec.parameters()``.

    The whole argument set dispatch checks: a selector spec's ``reads``, or a
    service spec's target selector's ``reads``, its own, then its Validator's
    parameters. A ``many`` service spec's is its ``reads`` and the one list
    its ``many_argument`` names, each row an object of the Validator's
    parameters. Pass the ``unknown_arguments`` the transport dispatches with,
    because the schema closes the argument set exactly when dispatch does.

    **A** ``partial`` **spec's Validator parameters are required nowhere**, at
    any depth - an object's fields and an array's rows included - because
    dispatch refuses none of them absent: a client reading ``required`` would
    otherwise never send the partial call the spec exists for. Its ``reads``
    and its target selector's keep their ``required``, as dispatch keeps
    them, so the schema still says which row a partial update names. On a
    ``many`` spec the list stays required and its rows' fields are not.
    ``parameters()`` itself is unchanged and still says what a whole call
    needs. Nothing else is relaxed: a read a ``kwargs`` provider fills is
    listed as declared, and ``server_owned_keys`` is how a transport finds it.
    Nor is anything a transport binds or withholds: this takes no
    ``ServerArguments``, and a transport subtracts its ``names()`` in the
    schema it builds, as it subtracts ``server_owned_keys``.

    Read on every call, as ``parameters()`` is, so a Validator reading a
    model-backed declaration is asked only once the app registry is ready.
    """
    # Relaxed by the shape check's own reading of ``partial``, so the schema
    # requires exactly what dispatch refuses absent, less what a provider fills.
    spec = kernel_spec(spec)
    parameters = relax_partial(spec, spec.parameters())
    return parameters_schema(parameters, unknown_arguments=unknown_arguments)
