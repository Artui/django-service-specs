from __future__ import annotations

from typing import Any

from django_service_specs.dispatch.utils import reach, server_filled
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.validation.validator_parameters import validator_parameters


def provider_reached(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    *,
    call_context: dict[str, Any] | None = None,
) -> frozenset[str]:
    """Every top-level parameter of ``spec`` a provider fills or may fill: what the shape check
    relaxes.

    Each provider's values reach one seat, and relax the parameters there: a
    ``kwargs`` provider its spec's ``reads``, a service spec's target
    selector's ``kwargs`` that selector's ``reads``, and, on a service spec
    that is not ``many``, ``input_data`` the Validator's fields. In its seat
    a typed provider reaches the keys its ``TypedDict`` names, ``filled`` and
    ``declinable`` alike, and one whose return says nothing about its keys
    reaches every parameter there
    ([`provider_keys`][django_service_specs.pool.provider_keys.provider_keys]).
    Less a read a provider requires itself, by name with no default: a
    provider is handed the caller's reads and the seeds, never another
    provider's answer, so the shape check demands it of the caller
    (test_a_read_its_provider_requires_is_not_reached).
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

    **Describe-time unless handed a context**: for a schema or a check made
    where a transport is built, it reads the Validator's fields as it declares
    them to no call, handing one that declares ``call_context`` ``None``
    (test_describe_time_readers_hand_none). The shape check relaxes each call
    by the parameters that call declares, so a transport describing the spec
    under a context of its own hands that dict here, and reads the set the
    shape check relaxes under it
    (test_a_field_declared_only_to_a_call_is_reached_under_that_call_s_context_alone,
    test_under_a_context_it_is_the_set_check_call_relaxes_under_it).

    ``spec`` may be a declaration with ``as_kernel_spec()``, read as the spec
    it compiles to.
    """
    spec = kernel_spec(spec)
    reached = server_filled(spec)[1]
    if isinstance(spec, ServiceSpec) and spec.validator is not None and not spec.many:
        fields = validator_parameters(spec.validator, call_context=call_context)
        reached |= reach(spec.input_data, fields)[1]
    return reached
