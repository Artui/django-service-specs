from __future__ import annotations

from typing_extensions import TypedDict

from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.pool.pool_seeds import PoolSeeds
from django_service_specs.pool.reserved_pool_seeds import RESERVED_POOL_SEEDS
from django_service_specs.schema.spec_input_schema import spec_input_schema
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.server_owned_keys import server_owned_keys
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.types.unset import UnsetType
from tests.specs.utils import PK, Bare, Foreign


class _Scope(TypedDict):
    tenant: str
    region: str | UnsetType


class _Project(TypedDict):
    project: int


class _Owner(TypedDict):
    owner: int


def scope() -> _Scope:
    return {"tenant": "acme", "region": "eu"}


def project() -> _Project:
    return {"project": 1}


def owner() -> _Owner:
    return {"owner": 1}


def untyped() -> dict:
    return {"anything": 1}


def listing(**kwargs: object) -> SelectorSpec:
    return SelectorSpec(
        kind=SelectorKind.LIST, selector=list, permissions=[Unrestricted()], **kwargs
    )


def test_a_spec_with_no_provider_owns_only_the_seeded_names() -> None:
    assert server_owned_keys(listing()) == RESERVED_POOL_SEEDS
    assert server_owned_keys(ServiceSpec(service=print)) == RESERVED_POOL_SEEDS


def test_the_shapes_seed_is_owned_and_never_asked_of_the_caller() -> None:
    """The seed is the server's; the shapes it carries are the caller's, by their own names."""
    shaped = listing(shapes=Parameters.of(Parameter("query", "string")))
    assert "shapes" in server_owned_keys(shaped)
    assert "query" not in server_owned_keys(shaped)
    assert set(spec_input_schema(shaped)["properties"]) == {"query"}


def test_the_keys_a_provider_fills_are_the_server_s_and_those_it_may_decline_are_not() -> None:
    # ``region`` admits ``UNSET``: the provider may step aside, so the
    # caller's value is the one the callable receives, and the key stays theirs.
    assert server_owned_keys(listing(kwargs=scope)) == RESERVED_POOL_SEEDS | {"tenant"}


def test_an_untyped_provider_owns_nothing_it_cannot_name() -> None:
    assert server_owned_keys(listing(kwargs=untyped)) == RESERVED_POOL_SEEDS


def test_a_registered_seed_is_owned_with_the_dispatcher_s_own() -> None:
    seeds = PoolSeeds().extend(request=lambda: None)
    assert server_owned_keys(listing(), pool_seeds=seeds) == RESERVED_POOL_SEEDS | {"request"}


def test_a_service_spec_owns_its_providers_and_its_target_lookup_s() -> None:
    # Each provider is one part of the union. A key one of them fills is the
    # server's for the whole call, because a parameter declaring it where
    # that provider's values never reach is refused when the spec is built.
    target = SelectorSpec(kind=SelectorKind.RETRIEVE, selector=list, reads=PK, kwargs=owner)
    spec = ServiceSpec(
        service=print,
        kwargs=scope,
        validator=Bare(),
        input_data=project,
        instance_selector_spec=target,
    )
    assert server_owned_keys(spec) == RESERVED_POOL_SEEDS | {"tenant", "project", "owner"}


def test_a_collection_lookup_s_provider_is_owned_too() -> None:
    target = SelectorSpec(kind=SelectorKind.LIST, selector=list, kwargs=owner)
    spec = ServiceSpec(service=print, collection_selector_spec=target)
    assert server_owned_keys(spec) == RESERVED_POOL_SEEDS | {"owner"}


def test_a_source_owns_what_the_spec_it_compiles_to_owns() -> None:
    spec = listing(kwargs=scope)

    assert server_owned_keys(Foreign(spec)) == server_owned_keys(spec)
    assert server_owned_keys(Foreign(spec)) > RESERVED_POOL_SEEDS
