"""A registry of specs as a management command."""

from django_service_specs.commands.add_spec_arguments import add_spec_arguments
from django_service_specs.commands.describe_parameters import describe_parameters
from django_service_specs.commands.parameter_descriptor import ParameterDescriptor
from django_service_specs.commands.parsed_arguments import parsed_arguments
from django_service_specs.commands.spec_command import SpecCommand
from django_service_specs.commands.unguarded_message import unguarded_message
from django_service_specs.commands.unguarded_reason import UnguardedReason
from django_service_specs.commands.unguarded_spec import UnguardedSpec
from django_service_specs.commands.unguarded_specs import unguarded_specs

__all__ = [
    "ParameterDescriptor",
    "SpecCommand",
    "UnguardedReason",
    "UnguardedSpec",
    "add_spec_arguments",
    "describe_parameters",
    "parsed_arguments",
    "unguarded_message",
    "unguarded_specs",
]
