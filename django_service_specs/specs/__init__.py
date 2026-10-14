"""The two declarations: a write and a read."""

from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.server_owned_keys import server_owned_keys
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource

__all__ = [
    "SelectorKind",
    "SelectorSpec",
    "ServiceSpec",
    "SpecSource",
    "kernel_spec",
    "server_owned_keys",
]
