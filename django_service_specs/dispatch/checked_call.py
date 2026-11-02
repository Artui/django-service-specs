"""``CheckedCall`` - what ``check_call`` returns: the checked arguments, the grant, and the seeds."""

from __future__ import annotations

from typing import Any

from django_service_specs.dispatch.call_seeds import CallSeeds
from django_service_specs.dispatch.grant import Grant


class CheckedCall(tuple[dict[str, Any], Grant]):
    """``(arguments, grant)``, as ``check_call`` has always returned, carrying the call's seeds.

    Still a 2-tuple, so ``arguments, grant = check_call(...)`` reads as it
    did. ``seeds`` is the
    [`CallSeeds`][django_service_specs.dispatch.call_seeds.CallSeeds] the
    checks were offered, for ``dispatch(grant=grant, seeds=checked.seeds)``.
    """

    # A tuple subclass takes no ``__slots__`` of its own, so the carrier sits
    # in the instance's dict, behind a read-only property.
    _seeds: CallSeeds

    def __new__(cls, arguments: dict[str, Any], grant: Grant, seeds: CallSeeds) -> CheckedCall:
        checked = super().__new__(cls, (arguments, grant))
        checked._seeds = seeds
        return checked

    @property
    def seeds(self) -> CallSeeds:
        """The values of the seeds a check names, as this call's checks were offered them."""
        return self._seeds
