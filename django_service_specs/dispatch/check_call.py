from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.dispatch.call_seeds import CallSeeds
from django_service_specs.dispatch.checked_call import CheckedCall
from django_service_specs.dispatch.grant import Grant
from django_service_specs.dispatch.utils import CheckKeywords, open_call
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.types.unknown_arguments import UnknownArguments


def check_call(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    *,
    principal: Any,
    arguments: Mapping[str, Any],
    grant: Grant | None = None,
    pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS,
    unknown_arguments: UnknownArguments = UnknownArguments.REJECT,
    call_context: dict[str, Any] | None = None,
) -> CheckedCall:
    """``dispatch``'s prelude, run alone: the checked arguments and the grant, or its refusal."""
    keywords = CheckKeywords({} if call_context is None else call_context)
    checked, granted = open_call(
        kernel_spec(spec),
        principal,
        arguments,
        grant=grant,
        pool_seeds=pool_seeds,
        unknown_arguments=unknown_arguments,
        settle_rows=True,
        keywords=keywords,
        carried=None,
    )
    seeds = CallSeeds(spec, principal, keywords.call_context, pool_seeds, keywords.seeds)
    return CheckedCall(checked, granted, seeds)
