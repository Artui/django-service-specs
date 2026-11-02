"""The readers that describe a spec outside any call hand its Validator no call context.

A Validator that opts into ``parameters(*, call_context=...)`` is handed the
call's dict on every ask inside a call, and ``None`` on every ask outside one.
A reader that registers, checks or describes a spec runs before any call
exists, so a dict it invented would tell the Validator a call is under way
and let it answer for a call that never comes.

``check_seeds`` and ``spec_input_schema`` hold the half for their own asks.
Here the readers in ``_READERS`` do the same: each row is a reader and a case
where that reader reaches its ask, and records what the Validator was handed.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from django_service_specs.dispatch.apply_server_arguments import apply_server_arguments
from django_service_specs.dispatch.check_requested_input import check_requested_input
from django_service_specs.dispatch.check_server_arguments import check_server_arguments
from django_service_specs.dispatch.provider_reached import provider_reached
from django_service_specs.dispatch.seed_named_parameters import seed_named_parameters
from django_service_specs.dispatch.unreceived_fields import unreceived_fields
from django_service_specs.schema.spec_caller_input_schema import spec_caller_input_schema
from django_service_specs.specs.server_owned_keys import server_owned_keys
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.server_arguments import ServerArguments
from tests.dispatch.utils import TENANT_SEEDS, every_ask_case

Reader = Callable[[ServiceSpec], object]


def _bound(spec: ServiceSpec) -> ServerArguments:
    """A value bound to a top-level parameter its declaration accepts."""
    if spec.many:
        return ServerArguments({spec.many_argument: [{"title": "Dune"}]})
    return ServerArguments({"title": "Dune"})


# Each reader is called with inputs that carry it to its ask and let it return.
# An empty schema, unlike ``None``, does not return before the ask, and names
# nothing a ``many`` spec's array parameter could not render. An empty
# ``ServerArguments`` is read by ``check_server_arguments`` but
# ``apply_server_arguments`` asks only to check a bound value, so it is handed one.
_READERS: dict[str, Reader] = {
    "check_server_arguments": lambda spec: check_server_arguments(
        spec, ServerArguments(), pool_seeds=TENANT_SEEDS
    ),
    "check_requested_input": lambda spec: check_requested_input(spec, {}, pool_seeds=TENANT_SEEDS),
    "apply_server_arguments": lambda spec: apply_server_arguments(spec, {}, _bound(spec)),
    "unreceived_fields": lambda spec: unreceived_fields(spec, pool_seeds=TENANT_SEEDS),
    "provider_reached": lambda spec: provider_reached(spec),
    "server_owned_keys": lambda spec: server_owned_keys(spec, pool_seeds=TENANT_SEEDS),
    "seed_named_parameters": lambda spec: seed_named_parameters(spec, pool_seeds=TENANT_SEEDS),
    "spec_caller_input_schema": lambda spec: spec_caller_input_schema(
        spec, pool_seeds=TENANT_SEEDS
    ),
}

# These three read the Validator's top-level fields, which a ``many`` spec does
# not have: its Validator's fields are each row's.
_SINGLE_ONLY = ("unreceived_fields", "provider_reached", "server_owned_keys")

_ROWS = [
    pytest.param(reader, case, id=f"{reader}-{case}")
    for reader in _READERS
    for case in ("single", "many")
    if not (case == "many" and reader in _SINGLE_ONLY)
]


@pytest.mark.parametrize(("reader", "case"), _ROWS)
def test_describe_time_readers_hand_none(reader: str, case: str) -> None:
    """A reader outside any call hands the Validator ``None``, never a dict."""
    spec, validator, _, _ = every_ask_case(case)
    _READERS[reader](spec)
    assert validator.asked
    assert validator.asked == [None] * len(validator.asked)
