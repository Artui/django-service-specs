from __future__ import annotations

import inspect

from django_service_specs.dispatch.utils import EVERY_POOL, seed_named_fields, target_entry
from django_service_specs.pool.call_seeds import CALL_SEEDS
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.pool.provider_keys import provider_keys
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource


def unreceived_fields(
    spec: ServiceSpec | SelectorSpec | SpecSource, *, pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS
) -> frozenset[str]:
    """The Validator fields of ``spec`` that its service takes by no route."""
    spec = kernel_spec(spec)
    if not isinstance(spec, ServiceSpec) or spec.validator is None:
        return frozenset()
    params = inspect.signature(spec.service).parameters
    named = frozenset(
        name
        for name, param in params.items()
        if param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    )
    fields = frozenset({spec.many_argument}) if spec.many else spec.validator.parameters().names()
    keys = provider_keys(spec.kwargs)
    if keys is None or named - (
        EVERY_POOL
        | pool_seeds.names
        | target_entry(spec, None).keys()
        | spec.reads.names()
        | fields
        | keys.filled
        | keys.declinable
    ):
        return frozenset()
    seed_named = seed_named_fields(spec, pool_seeds.names | CALL_SEEDS)
    takes_all = any(param.kind is inspect.Parameter.VAR_KEYWORD for param in params.values())
    if takes_all:
        return frozenset()
    return frozenset(name for name in fields if name in seed_named or name not in named)
