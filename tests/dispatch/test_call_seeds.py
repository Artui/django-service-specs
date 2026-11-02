"""The carrier ``check_call`` and ``resolve_target`` hand back on ``.seeds``, read on its own."""

from __future__ import annotations

import copy
import dataclasses
import pickle
from collections.abc import Callable
from typing import Any

import pytest

from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.dispatch.check_call import check_call
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS
from django_service_specs.specs.kernel_spec import kernel_spec
from tests.dispatch.utils import Tenancy, make_user
from tests.specs.utils import Foreign

pytestmark = pytest.mark.django_db


@pytest.fixture
def ada() -> Any:
    return make_user("ada")


def _minted(tenancy: Tenancy, spec: Any, principal: Any, context: dict[str, Any]) -> Any:
    return check_call(
        spec,
        principal=principal,
        arguments={"pk": 1},
        pool_seeds=tenancy.pool_seeds,
        call_context=context,
    ).seeds


def test_it_covers_exactly_its_spec_principal_call_context_and_registry(ada: Any) -> None:
    tenancy = Tenancy()
    spec, context = tenancy.spec(), {}
    seeds = _minted(tenancy, spec, ada, context)

    assert seeds.covers(spec, ada, context, tenancy.pool_seeds)
    # One arc to coverage, so each operand is held here by its own line.
    assert not seeds.covers(tenancy.spec(), ada, context, tenancy.pool_seeds)
    # Equal is not the same spec: a frozen dataclass compares by field, so only identity refuses it.
    assert not seeds.covers(dataclasses.replace(spec), ada, context, tenancy.pool_seeds)
    assert not seeds.covers(spec, make_user("bob"), context, tenancy.pool_seeds)
    assert not seeds.covers(spec, ada, {}, tenancy.pool_seeds)
    assert not seeds.covers(spec, ada, context, DEFAULT_POOL_SEEDS.extend(tenant=tenancy.tenant))


def test_minted_for_a_source_it_covers_the_source_and_the_spec_it_compiles_to(ada: Any) -> None:
    tenancy = Tenancy()
    source, context = Foreign(tenancy.spec()), {}
    seeds = _minted(tenancy, source, ada, context)

    assert seeds.spec is source
    assert seeds.covers(source, ada, context, tenancy.pool_seeds)
    assert seeds.covers(kernel_spec(source), ada, context, tenancy.pool_seeds)
    assert not seeds.covers(Foreign(tenancy.spec()), ada, context, tenancy.pool_seeds)


def test_it_holds_the_values_its_checks_were_offered(ada: Any) -> None:
    tenancy = Tenancy()
    seeds = _minted(tenancy, tenancy.spec(), ada, {})

    assert dict(seeds.values) == {"tenant": tenancy.resolved[0]}
    assert tenancy.one_value()


def test_its_values_are_a_read_only_copy(ada: Any) -> None:
    """A change to the dict it was built from, after it was built, reaches nothing it holds."""
    tenancy = Tenancy()
    seeds = _minted(tenancy, tenancy.spec(), ada, {})
    source = {"tenant": "acme"}
    built = dataclasses.replace(seeds, values=source)

    source["tenant"] = "changed"
    source["region"] = "eu"

    assert dict(built.values) == {"tenant": "acme"}
    with pytest.raises(TypeError):
        built.values["tenant"] = "changed"


@pytest.mark.parametrize("serialize", [pickle.dumps, copy.copy])
def test_a_carrier_cannot_be_pickled(ada: Any, serialize: Callable[[Any], object]) -> None:
    tenancy = Tenancy()
    seeds = _minted(tenancy, tenancy.spec(), ada, {})

    with pytest.raises(TypeError, match="cannot be serialized"):
        serialize(seeds)


def test_values_for_returns_the_values_of_a_covered_call_and_refuses_any_other(ada: Any) -> None:
    tenancy = Tenancy()
    spec, context = tenancy.spec(), {}
    seeds = _minted(tenancy, spec, ada, context)

    assert seeds.values_for(spec, ada, context, tenancy.pool_seeds) is seeds.values
    refused = [
        (dataclasses.replace(spec), ada, context, tenancy.pool_seeds),
        (spec, make_user("bob"), context, tenancy.pool_seeds),
        (spec, ada, {}, tenancy.pool_seeds),
        (spec, ada, None, tenancy.pool_seeds),
        (spec, ada, context, DEFAULT_POOL_SEEDS.extend(tenant=tenancy.tenant)),
    ]
    for call in refused:
        with pytest.raises(NotPermitted) as raised:
            seeds.values_for(*call)
        assert str(raised.value) == "The seeds do not cover this spec, principal and call context."
