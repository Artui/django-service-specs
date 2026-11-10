from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from django_service_specs.dispatch.apply_server_arguments import apply_server_arguments
from django_service_specs.dispatch.check_requested_input import check_requested_input
from django_service_specs.dispatch.check_server_arguments import check_server_arguments
from django_service_specs.dispatch.provider_reached import provider_reached
from django_service_specs.dispatch.seed_named_parameters import seed_named_parameters
from django_service_specs.dispatch.unreceived_fields import unreceived_fields
from django_service_specs.schema.spec_caller_input_schema import spec_caller_input_schema
from django_service_specs.schema.spec_input_schema import spec_input_schema
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
# not have: its Validator's fields are each row's. They have no row in ``_ROWS``
# for it; ``test_top_level_field_readers_ask_a_many_spec_nothing`` holds that
# they leave a ``many`` spec's Validator unasked.
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


@pytest.mark.parametrize("reader", _SINGLE_ONLY)
def test_top_level_field_readers_ask_a_many_spec_nothing(reader: str) -> None:
    """A reader of top-level fields never asks a ``many`` spec's Validator."""
    spec, validator, _, _ = every_ask_case("many")
    _READERS[reader](spec)
    assert validator.asked == []


_HANDED: dict[str, Callable[[ServiceSpec, dict[str, Any]], object]] = {
    "spec_caller_input_schema": lambda spec, context: spec_caller_input_schema(
        spec, pool_seeds=TENANT_SEEDS, call_context=context
    ),
    "spec_input_schema": lambda spec, context: spec_input_schema(spec, call_context=context),
    "provider_reached": lambda spec, context: provider_reached(spec, call_context=context),
}


@pytest.mark.parametrize(
    ("reader", "case"),
    [
        pytest.param(reader, case, id=f"{reader}-{case}")
        for reader in _HANDED
        for case in ("single", "many")
        if not (case == "many" and reader in _SINGLE_ONLY)
    ],
)
def test_a_reader_handed_a_context_hands_that_object_to_every_ask(reader: str, case: str) -> None:
    spec, validator, _, _ = every_ask_case(case)
    context: dict[str, Any] = {}

    _HANDED[reader](spec, context)

    assert validator.asked
    assert all(asked is context for asked in validator.asked)
