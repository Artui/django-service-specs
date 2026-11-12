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
    call_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """[`parameters_schema`][django_service_specs.schema.parameters_schema.parameters_schema] over
    ``spec.parameters()``.

    The whole argument set dispatch checks: a selector spec's ``reads`` and
    ``shapes``, or a service spec's target selector's ``reads``, its own, its
    ``shapes``, then its Validator's parameters. A ``many`` service spec's is
    its ``reads``, its ``shapes`` and the one list its ``many_argument``
    names, each row an object of the Validator's parameters. A shape is an
    argument like any other here, closed set included, though only the
    presenter reads it. Pass the ``unknown_arguments`` the transport dispatches with,
    because the schema closes the argument set exactly when dispatch does.

    **A** ``partial`` **spec's Validator parameters are required nowhere**, at
    any depth - an object's fields and an array's rows included - because
    dispatch refuses none of them absent: a client reading ``required`` would
    otherwise never send the partial call the spec exists for. Its ``reads``
    and its target selector's keep their ``required``, as dispatch keeps
    them, so the schema still says which row a partial update names. On a
    ``many`` spec the list stays required and its rows' fields are not.
    ``parameters()`` itself is unchanged and still says what a whole call
    needs. Nothing else is relaxed: a read a ``kwargs`` provider fills or may
    fill is listed as declared, ``required`` meaning the call needs the value
    from someone - the caller, or a provider that may fill it. A
    ``reflected`` read and a Validator field named like a registered seed are
    listed as declared too, and so is anything a transport binds or
    withholds: this takes no ``ServerArguments``. The schema a transport
    advertises, less what the server fills and with nothing a provider may
    fill required, at the top and in each row of a ``many`` spec, is
    [`spec_caller_input_schema`][django_service_specs.schema.spec_caller_input_schema.spec_caller_input_schema].

    Read on every call, as ``parameters()`` is, so a Validator reading a
    model-backed declaration is asked only once the app registry is ready.
    **Describe-time unless handed a context**: a schema describes the spec
    outside any call, so with no ``call_context`` a Validator that declares it
    is handed ``None`` (test_describe_time_readers_hand_none). A transport
    describing the spec under a context of its own hands that dict, and the
    Validator is asked with it, as ``spec.parameters(call_context=...)`` asks
    (test_a_field_declared_only_to_a_call_is_listed_under_that_call_s_context_alone).
    """
    spec = kernel_spec(spec)
    parameters = relax_partial(spec, spec.parameters(call_context=call_context))
    return parameters_schema(parameters, unknown_arguments=unknown_arguments)
