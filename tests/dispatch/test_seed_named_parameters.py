from __future__ import annotations

import re
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs import seed_named_parameters as exported
from django_service_specs.dispatch.check_call import check_call
from django_service_specs.dispatch.seed_named_parameters import seed_named_parameters
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
from tests.dispatch.utils import OPEN, Titled, make_user
from tests.specs.utils import Foreign

_SEEDED = DEFAULT_POOL_SEEDS.extend(tenant=lambda: "acme", title=lambda: "seeded")


def _reading(name: str, *, reflected: bool) -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.LIST,
        selector=lambda **_: [],
        permissions=OPEN,
        reads=Parameters.of(Parameter(name, "string", reflected=reflected)),
    )


def test_it_is_exported_from_the_root() -> None:
    assert exported is seed_named_parameters


def test_a_reflected_read_is_filled_and_an_unmarked_one_refused() -> None:
    assert seed_named_parameters(_reading("tenant", reflected=True), pool_seeds=_SEEDED) == (
        {"tenant"},
        frozenset(),
    )
    assert seed_named_parameters(_reading("tenant", reflected=False), pool_seeds=_SEEDED) == (
        frozenset(),
        {"tenant"},
    )


def test_a_name_no_seed_registers_is_in_neither_set() -> None:
    spec = _reading("tenant", reflected=False)
    assert seed_named_parameters(spec) == (frozenset(), frozenset())


def test_a_reflected_read_named_for_the_call_s_seat_is_filled_on_every_mount() -> None:
    assert seed_named_parameters(_reading("view", reflected=True)) == ({"view"}, frozenset())


def test_a_top_level_validator_field_is_the_caller_s() -> None:
    spec = ServiceSpec(service=lambda **_: None, permissions=OPEN, validator=Titled())
    assert seed_named_parameters(spec, pool_seeds=_SEEDED) == (frozenset(), frozenset())


def test_a_many_spec_s_list_named_for_the_call_s_seat_is_refused() -> None:
    spec = ServiceSpec(
        service=lambda **_: None,
        permissions=OPEN,
        many=True,
        many_argument="request",
        validator=Titled(),
    )
    assert seed_named_parameters(spec) == (frozenset(), {"request"})


def test_a_declaration_is_read_as_the_spec_it_compiles_to() -> None:
    spec = Foreign(_reading("tenant", reflected=False))
    assert seed_named_parameters(spec, pool_seeds=_SEEDED) == (frozenset(), {"tenant"})


@pytest.mark.django_db
@pytest.mark.parametrize("reflected", [False, True])
def test_it_is_the_answer_dispatch_gives(reflected: bool) -> None:
    """The second set is what dispatch refuses, by name; with it empty, the call starts."""
    spec = _reading("tenant", reflected=reflected)
    _, refused = seed_named_parameters(spec, pool_seeds=_SEEDED)
    call: dict[str, Any] = {"principal": make_user("ada"), "arguments": {}, "pool_seeds": _SEEDED}
    if refused:
        with pytest.raises(ImproperlyConfigured, match=re.escape(str(sorted(refused)))):
            check_call(spec, **call)
    else:
        check_call(spec, **call)
    assert bool(refused) is not reflected
