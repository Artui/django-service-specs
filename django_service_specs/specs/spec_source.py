from __future__ import annotations

from typing import Protocol

from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec


class SpecSource(Protocol):
    """An object that compiles itself to a ``ServiceSpec`` or ``SelectorSpec``."""

    def as_kernel_spec(self) -> ServiceSpec | SelectorSpec:
        """This declaration as a spec of this package's."""
        ...
