"""``UnguardedSpec`` - one registered spec that authorizes nothing, and why."""

from __future__ import annotations

from dataclasses import dataclass

from django_service_specs.commands.unguarded_reason import UnguardedReason


@dataclass(frozen=True)
class UnguardedSpec:
    """A registry entry whose spec any principal may run.

    Fields:

    - **``name``** - the name the spec is registered under, which is the
      subcommand an operator types.
    - **``reason``** - the
      [`UnguardedReason`][django_service_specs.commands.unguarded_reason.UnguardedReason]
      its declaration falls under.
    """

    name: str
    reason: UnguardedReason
