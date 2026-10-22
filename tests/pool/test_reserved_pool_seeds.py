from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS
from django_service_specs.pool.reserved_pool_seeds import RESERVED_POOL_SEEDS
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.selector_kind import SelectorKind

CALL_CONTEXT = Parameters.of(Parameter("call_context", "object"))


def test_the_call_s_context_is_a_name_dispatch_owns() -> None:
    assert "call_context" in RESERVED_POOL_SEEDS


@pytest.mark.parametrize(
    "declare",
    [
        lambda: ServiceSpec(service=print, reads=CALL_CONTEXT),
        lambda: SelectorSpec(kind=SelectorKind.LIST, selector=list, reads=CALL_CONTEXT),
    ],
    ids=["service-spec", "selector-spec"],
)
def test_a_parameter_named_call_context_is_refused(declare: object) -> None:
    """A caller's argument may never stand in for the transport's dict."""
    with pytest.raises(ImproperlyConfigured, match="call_context"):
        declare()  # ty: ignore[call-non-callable]


def test_a_seed_named_call_context_is_refused() -> None:
    with pytest.raises(ValueError, match="call_context"):
        DEFAULT_POOL_SEEDS.extend(call_context=dict)
