from __future__ import annotations

from typing import Any, NoReturn

from django_service_specs.dispatch.call_seeds import CallSeeds
from django_service_specs.dispatch.grant import Grant


class CheckedCall(tuple[dict[str, Any], Grant]):
    """``(arguments, grant)``, as ``check_call`` has always returned, carrying the call's seeds."""

    _seeds: CallSeeds

    def __new__(cls, arguments: dict[str, Any], grant: Grant, seeds: CallSeeds) -> CheckedCall:
        checked = super().__new__(cls, (arguments, grant))
        checked._seeds = seeds
        return checked

    def __reduce__(self) -> NoReturn:
        # Refused here: ``copy`` and pickle rebuild a tuple subclass through ``__new__``.
        return self._seeds.__reduce__()

    @property
    def seeds(self) -> CallSeeds:
        """The values of the seeds a check names, as this call's checks were offered them."""
        return self._seeds
