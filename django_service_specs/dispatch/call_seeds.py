from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, NoReturn

from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.pool.pool_seeds import PoolSeeds
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource


@dataclass(frozen=True, eq=False)
class CallSeeds:
    """The values of the registered seeds a check names, as one call's prelude resolved them."""

    spec: ServiceSpec | SelectorSpec | SpecSource
    principal: Any
    call_context: dict[str, Any]
    pool_seeds: PoolSeeds
    values: Mapping[str, Any]

    def __post_init__(self) -> None:
        # A copy, so the call's own dict never reaches the carrier later.
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))

    def covers(
        self,
        spec: ServiceSpec | SelectorSpec | SpecSource,
        principal: Any,
        call_context: dict[str, Any] | None,
        pool_seeds: PoolSeeds,
    ) -> bool:
        """Whether these values are this call's: its spec, principal, context and registry."""
        return (
            kernel_spec(self.spec) is kernel_spec(spec)
            and self.principal is principal
            and call_context is not None
            and self.call_context is call_context
            and self.pool_seeds is pool_seeds
        )

    def values_for(
        self,
        spec: ServiceSpec | SelectorSpec | SpecSource,
        principal: Any,
        call_context: dict[str, Any] | None,
        pool_seeds: PoolSeeds,
    ) -> Mapping[str, Any]:
        """These values for a call they ``cover``; ``NotPermitted`` otherwise."""
        if self.covers(spec, principal, call_context, pool_seeds):
            return self.values
        raise NotPermitted("The seeds do not cover this spec, principal and call context.")

    def __reduce__(self) -> NoReturn:
        raise TypeError(
            "CallSeeds belong to one call in one process and cannot be serialized. "
            "A worker resolves its own."
        )
