from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NoReturn

from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource


@dataclass(frozen=True)
class Grant:
    """Proof that the class-level check already ran, for one spec and one principal."""

    spec: ServiceSpec | SelectorSpec | SpecSource
    principal: Any
    target_checked: bool = False

    def covers(self, spec: ServiceSpec | SelectorSpec | SpecSource, principal: Any) -> bool:
        """Whether this grant is for exactly this spec and this principal."""
        return self.principal is principal and kernel_spec(self.spec) is kernel_spec(spec)

    def __reduce__(self) -> NoReturn:
        raise TypeError(
            "A Grant covers one call in one process and cannot be serialized. "
            "A worker re-authorizes with the principal it resolves."
        )
