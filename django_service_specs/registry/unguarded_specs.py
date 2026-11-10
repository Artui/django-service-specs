from __future__ import annotations

from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.registry.spec_registry import SpecRegistry
from django_service_specs.registry.unguarded_spec import UnguardedSpec
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.types.unguarded_reason import UnguardedReason


def unguarded_specs(registry: SpecRegistry) -> tuple[UnguardedSpec, ...]:
    """The entries of ``registry`` that any principal may run, in registry order."""
    return tuple(
        UnguardedSpec(entry.name, UnguardedReason.UNRESTRICTED)
        for entry in registry
        if all(
            isinstance(check, Unrestricted) for check in kernel_spec(entry.spec).permissions or ()
        )
    )
