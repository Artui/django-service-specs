from __future__ import annotations

from dataclasses import replace

from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec


def relax_partial(spec: ServiceSpec | SelectorSpec, parameters: Parameters) -> Parameters:
    """``parameters`` as a call of ``spec`` is checked under ``partial``: all optional."""
    if not (isinstance(spec, ServiceSpec) and spec.partial):
        return parameters
    if spec.many:
        return Parameters.of(
            *(_below(param) if param.name == spec.many_argument else param for param in parameters)
        )
    target = spec.target_selector_spec()
    kept = (
        spec.reads.names()
        | spec.shapes.names()
        | (target.parameters().names() if target is not None else frozenset())
    )
    return Parameters.of(
        *(param if param.name in kept else _optional(param) for param in parameters)
    )


def _optional(param: Parameter) -> Parameter:
    """``param`` and everything declared below it made optional, as a partial serializer reads it."""
    return replace(_below(param), required=False)


def _below(param: Parameter) -> Parameter:
    """``param`` with everything declared below it optional: an object's fields, an array's rows."""
    items = param.items
    return replace(
        param,
        fields=None if param.fields is None else Parameters.of(*map(_optional, param.fields)),
        items=Parameters.of(*map(_optional, items)) if isinstance(items, Parameters) else items,
    )
