from __future__ import annotations

from django_service_specs.dispatch.provider_reached import provider_reached
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance_declarer import AffordanceDeclarer
from django_service_specs.types.spec_link import SpecLink


def required_reads(declared: AffordanceDeclarer) -> tuple[str, ...]:
    """The target's required reads the shape check demands of a caller, which a row must fill."""
    spec = declared.spec if isinstance(declared, SpecLink) else declared
    if not isinstance(spec, ServiceSpec):
        return ()
    target = spec.target_selector_spec()
    if target is None:
        return ()
    reached = provider_reached(spec)
    return tuple(read.name for read in target.reads if read.required and read.name not in reached)
