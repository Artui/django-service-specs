"""A registry of specs as a management command."""

from django_service_specs.commands.spec_command import SpecCommand
from django_service_specs.commands.unguarded_message import unguarded_message
from django_service_specs.commands.unguarded_reason import UnguardedReason
from django_service_specs.commands.unguarded_spec import UnguardedSpec
from django_service_specs.commands.unguarded_specs import unguarded_specs

__all__ = [
    "SpecCommand",
    "UnguardedReason",
    "UnguardedSpec",
    "unguarded_message",
    "unguarded_specs",
]
