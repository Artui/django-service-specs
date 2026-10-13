"""``spec_input_schema`` - the JSON Schema of what a spec takes."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
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

    Read on every call, as ``parameters()`` is, so a Validator reading a
    model-backed declaration is asked only once the app registry is ready.
    """
    parameters = spec.parameters()
    # One branch to coverage, so each condition is held by its own test:
    # test_a_selector_specs_schema_is_its_reads (the type: a selector spec has
    # no ``partial``, so without it the attribute is missing) and
    # test_a_spec_that_is_not_partial_requires_every_required_parameter.
    if isinstance(spec, ServiceSpec) and spec.partial:
        parameters = _partial(spec, parameters)
    return parameters_schema(parameters, unknown_arguments=unknown_arguments)


def _partial(spec: ServiceSpec, parameters: Parameters) -> Parameters:
    """``parameters`` as dispatch checks a partial call of ``spec``: the Validator's optional throughout.

    The Validator's are told apart by what they are not, the spec's reads and
    its target's, so the Validator is not asked for its parameters again. On a
    ``many`` spec they are the list's rows, and a read may share a row field's
    name, so only the list is walked
    (test_a_partial_many_spec_requires_the_list_and_its_reads_and_nothing_in_a_row).
    """
    if spec.many:
        return Parameters.of(
            *(_below(param) if param.name == spec.many_argument else param for param in parameters)
        )
    target = spec.target_selector_spec()
    # The spec's reads are held by
    # test_a_partial_spec_with_no_target_keeps_its_reads_required, the
    # target's by test_a_partial_spec_requires_none_of_its_validators_parameters_at_any_depth.
    kept = spec.reads.names() | (target.parameters().names() if target is not None else frozenset())
    return Parameters.of(
        *(param if param.name in kept else _optional(param) for param in parameters)
    )


def _optional(param: Parameter) -> Parameter:
    """``param`` and everything declared below it made optional, as dispatch's partial check reads it."""
    return replace(_below(param), required=False)


def _below(param: Parameter) -> Parameter:
    """``param`` with everything declared below it optional: an object's fields, an array's rows."""
    items = param.items
    return replace(
        param,
        fields=None if param.fields is None else Parameters.of(*map(_optional, param.fields)),
        items=Parameters.of(*map(_optional, items)) if isinstance(items, Parameters) else items,
    )
