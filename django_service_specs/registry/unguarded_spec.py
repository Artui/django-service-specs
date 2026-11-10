from __future__ import annotations

from dataclasses import dataclass

from django_service_specs.types.unguarded_reason import UnguardedReason


@dataclass(frozen=True)
class UnguardedSpec:
    """A registry entry whose spec any principal may run."""

    name: str
    reason: UnguardedReason
