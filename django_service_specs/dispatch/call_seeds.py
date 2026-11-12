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
    """The values of the registered seeds a check names, as one call's prelude resolved them.

    [`check_call`][django_service_specs.dispatch.check_call.check_call] and
    [`resolve_target`][django_service_specs.dispatch.resolve_target.resolve_target]
    hand one back on ``.seeds``, beside their grant, for ``dispatch(seeds=)``
    and ``adispatch(seeds=)``.
    [`resolve_seeds`][django_service_specs.dispatch.resolve_seeds.resolve_seeds]
    makes one ahead of ``authorize``, for a transport that admits a call before
    it resolves the row: ``authorize``, ``authorize_scope``,
    ``authorize_target`` and ``resolve_target`` take it as ``seeds=`` too.
    Each then takes these values as they are,
    resolving none of those seeds again, so the checks the prelude asked and
    the run that follows - the object-level check, the selectors, the service
    and the presenter - see one value of each. Without it, each seed a check
    names is resolved once by the prelude and once more by dispatch.

    ``values`` holds only the seeds a check of the spec names, at any of its
    three questions; every other seed resolves in each pool as it always does.
    It is a read-only copy, taken when the carrier is built, so nothing the
    prelude's dict meets afterwards reaches it.

    **Bound to one call**, by identity: the spec (compared as compiled, as a
    [`Grant`][django_service_specs.dispatch.grant.Grant] compares it), the
    principal, the ``call_context`` dict and the ``pool_seeds`` registry.
    Where a grant can be reused across calls, a carrier is for the call whose
    context it was minted with, and its names are that registry's. Dispatch
    refuses one that does not cover its call as ``NotPermitted``, and so does
    every function that takes one, through
    [`values_for`][django_service_specs.dispatch.call_seeds.CallSeeds.values_for].

    **Not serializable**, as a grant is not: pickling one raises ``TypeError``.
    """

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
        """Whether these values are this call's: its spec, its principal, its context and registry.

        Each by identity, the spec as compiled, as
        [`Grant.covers`][django_service_specs.dispatch.grant.Grant.covers]
        compares it: a carrier minted for a ``SpecSource`` covers that object
        and the spec it compiles to. A carrier is always bound to a dict, so a
        call handed no ``call_context`` (``None``) is covered by none.
        """
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
        """These values, for a call they
        [`cover`][django_service_specs.dispatch.call_seeds.CallSeeds.covers]; ``NotPermitted``
        otherwise.

        The one place a carrier for another spec, principal, call context or
        registry is refused, for every function that takes one: ``dispatch``
        and ``adispatch``, ``resolve_target``, and the three ``authorize``
        functions. Values resolved for another call are never read as this
        one's, and never quietly replaced by fresh ones either
        (test_values_for_returns_the_values_of_a_covered_call_and_refuses_any_other).

        Raises:
            NotPermitted: the carrier does not cover this call.
        """
        if self.covers(spec, principal, call_context, pool_seeds):
            return self.values
        raise NotPermitted("The seeds do not cover this spec, principal and call context.")

    def __reduce__(self) -> NoReturn:
        raise TypeError(
            "CallSeeds belong to one call in one process and cannot be serialized. "
            "A worker resolves its own."
        )
