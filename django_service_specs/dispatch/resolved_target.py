"""``ResolvedTarget`` - what ``resolve_target`` returns: the target, its grant, and the seeds."""

from __future__ import annotations

from typing import Any

from django_service_specs.dispatch.call_seeds import CallSeeds
from django_service_specs.dispatch.grant import Grant


class ResolvedTarget(tuple[Any, Grant]):
    """``(target, grant)``, as ``resolve_target`` has always returned, carrying the call's seeds.

    Still a 2-tuple, so ``target, grant = resolve_target(...)`` reads as it
    did. ``seeds`` is the
    [`CallSeeds`][django_service_specs.dispatch.call_seeds.CallSeeds] the
    class-level check and the checks on the target were offered, for
    ``dispatch(target=target, grant=grant, seeds=found.seeds)``.
    """

    # A tuple subclass takes no ``__slots__`` of its own, so the carrier sits
    # in the instance's dict, behind a read-only property.
    _seeds: CallSeeds

    def __new__(cls, target: Any, grant: Grant, seeds: CallSeeds) -> ResolvedTarget:
        found = super().__new__(cls, (target, grant))
        found._seeds = seeds
        return found

    @property
    def seeds(self) -> CallSeeds:
        """The values of the seeds a check names, as this call's checks were offered them."""
        return self._seeds
