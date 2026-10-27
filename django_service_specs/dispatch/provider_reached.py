"""``provider_reached`` - the parameters a provider fills or may fill, which dispatch does not demand."""

from __future__ import annotations

from django_service_specs.dispatch.utils import reach, server_filled
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource


def provider_reached(spec: ServiceSpec | SelectorSpec | SpecSource) -> frozenset[str]:
    """Every top-level parameter of ``spec`` a provider fills or may fill: what the shape check relaxes.

    Each provider's values reach one seat, and relax the parameters there: a
    ``kwargs`` provider its spec's ``reads``, a service spec's target
    selector's ``kwargs`` that selector's ``reads``, and, on a service spec
    that is not ``many``, ``input_data`` the Validator's fields. In its seat
    a typed provider reaches the keys its ``TypedDict`` names, ``filled`` and
    ``declinable`` alike, and one whose return says nothing about its keys
    reaches every parameter there
    ([`provider_keys`][django_service_specs.pool.provider_keys.provider_keys]).
    The shape check does not demand a parameter this names, and a transport
    reading it leaves such a parameter out of the arguments its schema
    requires; one a provider is annotated to fill, and may not decline, is
    in [`server_owned_keys`][django_service_specs.specs.server_owned_keys.server_owned_keys]
    too, which leaves it out of the schema altogether.

    The same reader the shape check relaxes by, so a transport's schema and
    dispatch cannot disagree about which parameter a caller must send
    (test_it_is_the_set_check_call_relaxes).
    ``check_server_arguments`` reads it, so a parameter the shape check does
    not demand may be withheld. One arc to coverage, each conjunct held by
    its own test: a selector spec has no Validator
    (test_check_server_arguments_lets_a_read_an_untyped_provider_reaches_be_withheld),
    a service spec may have none
    (test_a_service_spec_s_read_is_judged_by_its_service), and a ``many``
    spec's row fields are no top-level parameter, though one may share a
    read's name
    (test_check_server_arguments_still_refuses_withholding_a_many_read_a_row_field_shares).

    ``spec`` may be a declaration with ``as_kernel_spec()``, read as the spec
    it compiles to.
    """
    spec = kernel_spec(spec)
    reached = server_filled(spec)[1]
    if isinstance(spec, ServiceSpec) and spec.validator is not None and not spec.many:
        reached |= reach(spec.input_data, spec.validator.parameters())[1]
    return reached
