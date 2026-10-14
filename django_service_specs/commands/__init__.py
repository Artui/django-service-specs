"""A registry of specs as a management command."""

from django_service_specs.commands.add_spec_arguments import add_spec_arguments
from django_service_specs.commands.describe_parameters import describe_parameters
from django_service_specs.commands.parameter_descriptor import ParameterDescriptor
from django_service_specs.commands.parsed_arguments import parsed_arguments
from django_service_specs.commands.spec_command import SpecCommand

__all__ = [
    "ParameterDescriptor",
    "SpecCommand",
    "add_spec_arguments",
    "describe_parameters",
    "parsed_arguments",
]
