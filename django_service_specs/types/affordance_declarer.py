from __future__ import annotations

from collections.abc import Sequence

from django_service_specs.types.affordance import Affordance


class AffordanceDeclarer:
    """A spec that declares the conditions an operation needs: a ``ServiceSpec``."""

    @property
    def affordances(self) -> Sequence[Affordance] | None: ...

    def link_reads(self) -> tuple[str, ...]:
        """The reads a row's link may bind; none, unless a spec says."""
        return ()
