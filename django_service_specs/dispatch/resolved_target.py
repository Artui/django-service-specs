from __future__ import annotations

from typing import Any, NoReturn

from django_service_specs.dispatch.call_seeds import CallSeeds
from django_service_specs.dispatch.grant import Grant


class ResolvedTarget(tuple[Any, Grant]):
    """``(target, grant)``, as ``resolve_target`` has always returned, carrying the call's seeds."""

    _seeds: CallSeeds

    def __new__(cls, target: Any, grant: Grant, seeds: CallSeeds) -> ResolvedTarget:
        found = super().__new__(cls, (target, grant))
        found._seeds = seeds
        return found

    def __reduce__(self) -> NoReturn:
        # Refused here: ``copy`` and pickle rebuild a tuple subclass through ``__new__``.
        return self._seeds.__reduce__()

    @property
    def seeds(self) -> CallSeeds:
        """The values of the seeds a check names, as this call's checks were offered them."""
        return self._seeds
