"""``relax_partial`` - what a partial call of a spec may leave out."""

from __future__ import annotations

from dataclasses import replace

from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec


def relax_partial(spec: ServiceSpec | SelectorSpec, parameters: Parameters) -> Parameters:
    """``parameters`` as a call of ``spec`` is checked under ``partial``: every Validator parameter optional.

    The one reading of what a partial call may leave out, for the shape check
    and for ``spec_input_schema``'s ``required``, so the schema never asks for
    a field dispatch would not refuse absent, nor leaves one out that it
    would. Made optional at every depth - an object's fields and an array's
    rows included - as djangorestframework-services relaxes only its
    serializer. The spec's ``reads`` and its target selector's keep their
    ``required``: a partial update still names the row it updates
    (test_a_partial_call_omitting_the_target_s_pk_is_refused_at_the_shape_check).
    So do its ``shapes``, which say what is presented rather than what is
    written, as on a ``many`` spec, where only the list's rows are walked.
    On a ``many`` spec the Validator's parameters are each row's, so the list
    stays required and only its rows are walked, since a read may share a
    row field's name
    (test_a_partial_many_spec_requires_the_list_and_its_reads_and_nothing_in_a_row).

    ``parameters`` as they are for a selector spec, which has no ``partial``,
    and for a service spec that is not partial. One branch to coverage, so
    each condition is held by its own test:
    test_a_selector_specs_schema_is_its_reads (the type: without it, a
    selector spec's missing attribute raises) and
    test_a_spec_that_is_not_partial_requires_every_required_parameter (the
    flag). The Validator's are told apart by what they are not, the spec's
    reads and its target's, so the Validator is not asked for its parameters
    again; a read and a Validator parameter of one name are refused when
    ``parameters()`` is assembled. Of the names kept, the spec's reads are
    held by test_a_partial_spec_with_no_target_keeps_its_reads_required, the
    shapes by test_a_partial_spec_keeps_a_required_shape_required, and the
    target's by
    test_a_partial_spec_requires_none_of_its_validators_parameters_at_any_depth.

    A copy, so the declaration every other reader sees - ``parameters()``
    itself, which still says what a whole call needs - is untouched.

    Public so that a transport building an input surface of its own - a
    command's options, a form - asks a partial call for what dispatch asks,
    rather than restating the rule and drifting from it.
    """
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
