from __future__ import annotations

from collections.abc import Sequence

from django_service_specs.types.affordance import Affordance


class AffordanceDeclarer:
    """A spec that declares the conditions an operation needs: a ``ServiceSpec``."""

    @property
    def affordances(self) -> Sequence[Affordance] | None: ...

    def link_reads(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """``(required, optional)``: the reads a row's link may fill; none, unless a spec says."""
        return (), ()
