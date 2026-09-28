"""What an operation takes, and the refusal of arguments that do not fit."""

from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters

__all__ = ["InvalidArguments", "Parameter", "Parameters"]
