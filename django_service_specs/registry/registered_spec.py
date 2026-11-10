from __future__ import annotations

from dataclasses import dataclass

from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource


@dataclass(frozen=True)
class RegisteredSpec:
    """A spec under its canonical name, with free-form tags."""

    name: str
    spec: ServiceSpec | SelectorSpec | SpecSource
    tags: frozenset[str] = frozenset()
