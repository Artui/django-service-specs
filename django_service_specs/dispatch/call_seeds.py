"""``CallSeeds`` - the registered seeds a call's checks were offered, handed on to its run."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, NoReturn

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
    and ``adispatch(seeds=)``. Dispatch then takes these values as they are,
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
    refuses one that does not cover its call as ``NotPermitted``.

    **Not serializable**, as a grant is not: pickling one raises ``TypeError``.
    """

    spec: ServiceSpec | SelectorSpec | SpecSource
    principal: Any
    call_context: dict[str, Any]
    pool_seeds: PoolSeeds
    values: Mapping[str, Any]

    def __post_init__(self) -> None:
        # A copy, here, so whoever builds one hands it the call's own dict and
        # what that dict meets later never reaches the carrier
        # (test_its_values_are_a_read_only_copy).
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))

    def covers(
        self,
        spec: ServiceSpec | SelectorSpec | SpecSource,
        principal: Any,
        call_context: dict[str, Any],
        pool_seeds: PoolSeeds,
    ) -> bool:
        """Whether these values are this call's: its spec, its principal, its context and registry.

        Each by identity, the spec as compiled, as
        [`Grant.covers`][django_service_specs.dispatch.grant.Grant.covers]
        compares it: a carrier minted for a ``SpecSource`` covers that object
        and the spec it compiles to.
        """
        # One arc to coverage, so each operand is named:
        # test_it_covers_exactly_its_spec_principal_call_context_and_registry
        # holds the four, test_a_carrier_for_another_{spec,principal}_is_refused,
        # test_a_carrier_from_another_call_is_refused and
        # test_a_carrier_under_another_registry_is_refused each one through
        # dispatch, and test_a_carrier_for_a_source_covers_its_compiled_spec the
        # compile, without which a carrier minted for a source covers nothing.
        return (
            kernel_spec(self.spec) is kernel_spec(spec)
            and self.principal is principal
            and self.call_context is call_context
            and self.pool_seeds is pool_seeds
        )

    def __reduce__(self) -> NoReturn:
        raise TypeError(
            "CallSeeds belong to one call in one process and cannot be serialized. "
            "A worker resolves its own."
        )
