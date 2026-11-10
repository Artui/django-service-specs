from __future__ import annotations

from django_service_specs.dispatch.utils import split_seed_named
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource


def seed_named_parameters(
    spec: ServiceSpec | SelectorSpec | SpecSource, *, pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS
) -> tuple[frozenset[str], frozenset[str]]:
    """Of ``spec``'s parameters named like a seed: those filled, and those refused."""
    spec = kernel_spec(spec)
    return split_seed_named(spec, spec.parameters(), pool_seeds)
